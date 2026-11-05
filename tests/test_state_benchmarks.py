# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Measure input-state construction, retry collection, and real update fallback."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from conda.base.constants import UpdateModifier
from conda.base.context import context, reset_context
from conda.core.package_cache_data import PackageCacheData
from conda.core.prefix_data import PrefixData
from conda.core.subdir_data import SubdirData
from conda.models.channel import Channel
from conda.models.records import PrefixRecord

from conda_rattler_solver.solver import RattlerSolver
from conda_rattler_solver.state import SolverInputState, SolverOutputState

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.fixture
def state_benchmark_prefix(tmp_path: Path, monkeypatch: MonkeyPatch) -> Iterator[Path]:
    try:
        with monkeypatch.context() as patch:
            for name, value in {
                "CONDARC": str(tmp_path / "condarc"),
                "CONDA_PKGS_DIRS": str(tmp_path / "pkgs"),
                "CONDA_AGGRESSIVE_UPDATE_PACKAGES": "",
                "CONDA_PINNED_PACKAGES": "",
                "CONDA_AUTO_UPDATE_CONDA": "false",
                "CONDA_NOTIFY_OUTDATED_CONDA": "false",
                "CONDA_REPODATA_USE_SHARDS": "false",
                "CONDA_REPODATA_USE_ZST": "false",
                "CONDA_OFFLINE": "true",
                "CONDA_QUIET": "true",
            }.items():
                patch.setenv(name, value)
            reset_context()
            prefix = tmp_path / "prefix"
            (prefix / "conda-meta").mkdir(parents=True)
            (prefix / "conda-meta" / "history").touch()
            yield prefix
    finally:
        reset_context()


@pytest.mark.benchmark
@pytest.mark.parametrize("package_count", (100, 563, 1000))
@pytest.mark.parametrize("collection", ("first", "retry"))
def test_state_spec_collection_benchmark(
    benchmark: BenchmarkFixture,
    state_benchmark_prefix: Path,
    package_count: int,
    collection: str,
) -> None:
    """The first case includes input construction, the retry rebuilds output state."""
    prefix = state_benchmark_prefix
    names = tuple(f"package-{index:04}" for index in range(package_count))
    prefix_data = PrefixData(prefix)
    for name in names:
        prefix_data._prefix_records[name] = PrefixRecord(
            name=name,
            version="1.0",
            build="0",
            build_number=0,
            channel="conda-forge",
            subdir="noarch",
            fn=f"{name}-1.0-0.conda",
        )
    solver = RattlerSolver(prefix, channels=(), command="update")

    def collect(state):
        output = SolverOutputState(solver_input_state=state)
        return solver._collect_specs_main(state, output)

    def first():
        return collect(
            SolverInputState(prefix, update_modifier=UpdateModifier.UPDATE_ALL, command="update")
        )

    def prepare_retry():
        state = SolverInputState(
            prefix, update_modifier=UpdateModifier.UPDATE_ALL, command="update"
        )
        collect(state)
        return (state,), {}

    collected = benchmark.pedantic(
        first if collection == "first" else collect,
        setup=prepare_retry if collection == "retry" else None,
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )

    assert sorted(str(spec) for spec in collected["specs"]) == list(names)
    assert sorted(str(spec) for spec in collected["constraints"]) == [
        f"{name} >=1.0" for name in names
    ]
    assert collected["locked_packages"] == []
    assert collected["pinned_packages"] == []


@pytest.mark.benchmark
def test_state_update_fallback_benchmark(
    benchmark: BenchmarkFixture,
    state_benchmark_prefix: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Time a complete 563-package solve requiring three actual Rattler attempts."""
    prefix = state_benchmark_prefix
    channel = prefix.parent / "channel"
    metadata = prefix / "conda-meta"
    packages = {}
    installed = []

    def add(name, version="1.0", build="0", depends=(), is_installed=False):
        filename = f"{name}-{version}-{build}.tar.bz2"
        record = {
            "name": name,
            "version": version,
            "build": build,
            "build_number": int(build),
            "depends": list(depends),
            "subdir": "noarch",
            "noarch": "generic",
            "md5": "0" * 32,
            "sha256": "0" * 64,
            "size": 1,
            "timestamp": 0,
        }
        packages[filename] = record
        if is_installed:
            installed.append(f"+{channel.as_uri()}/noarch::{name}-{version}-{build}")
            (metadata / f"{name}-{version}-{build}.json").write_text(
                json.dumps(
                    {
                        **record,
                        "fn": filename,
                        "channel": channel.as_uri(),
                        "url": (channel / "noarch" / filename).as_uri(),
                        "files": [],
                    }
                )
            )

    add("dep", build="2", is_installed=True)
    add("app", depends=("dep 1.0 2",), is_installed=True)
    add("dep")
    add("app", version="2.0", depends=("dep 1.0 0",))
    for number in range(561):
        add(f"filler-{number:04}", is_installed=True)

    for subdir in (context.subdir, "noarch"):
        directory = channel / subdir
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "repodata.json").write_text(
            json.dumps(
                {
                    "info": {"subdir": subdir},
                    "packages": packages if subdir == "noarch" else {},
                    "packages.conda": {},
                    "repodata_version": 1,
                }
            )
        )
    (metadata / "pinned").write_text("app >=2\n")
    (metadata / "history").write_text(
        "\n".join(
            ["==> 2026-11-05 00:00:00 <==", *installed, "# update specs: ['app', 'dep']", ""]
        )
    )

    attempts = []
    solve_attempt = RattlerSolver._solve_attempt

    def counted_attempt(self, *args, **kwargs):
        attempts.append(None)
        return solve_attempt(self, *args, **kwargs)

    monkeypatch.setattr(RattlerSolver, "_solve_attempt", counted_attempt)

    def prepare():
        attempts.clear()
        SubdirData.clear_cached_local_channel_data(exclude_file=False)
        PackageCacheData.clear()

    def solve():
        solver = RattlerSolver(
            prefix,
            channels=(Channel(str(channel)),),
            subdirs=(context.subdir, "noarch"),
            specs_to_add=("app",),
            command="update",
        )
        return solver.solve_for_diff(update_modifier=UpdateModifier.UPDATE_SPECS)

    unlink, link = benchmark.pedantic(
        solve, setup=prepare, rounds=5, iterations=1, warmup_rounds=1
    )

    assert len(attempts) == 3
    assert sorted((record.name, record.version, record.build) for record in unlink) == [
        ("app", "1.0", "0"),
        ("dep", "1.0", "2"),
    ]
    assert sorted((record.name, record.version, record.build) for record in link) == [
        ("app", "2.0", "0"),
        ("dep", "1.0", "0"),
    ]
