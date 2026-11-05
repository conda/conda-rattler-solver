# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Local benchmarks for pin validation and package-cache solver sources."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest
import rattler
from conda.base.context import context, reset_context
from conda.core.package_cache_data import PackageCacheData
from conda.core.subdir_data import SubdirData
from conda.models.channel import Channel

from conda_rattler_solver.index import RattlerIndexHelper
from conda_rattler_solver.solver import RattlerSolver

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture


@pytest.fixture
def isolated_package_cache(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    cache = tmp_path / "pkgs"
    cache.mkdir()
    for name, value in {
        "CONDA_PKGS_DIRS": str(cache),
        "CONDA_AGGRESSIVE_UPDATE_PACKAGES": "",
        "CONDA_PINNED_PACKAGES": "",
        "CONDA_NOTIFY_OUTDATED_CONDA": "false",
        "CONDA_REPODATA_USE_SHARDS": "false",
        "CONDA_REPODATA_USE_ZST": "false",
        "CONDA_QUIET": "true",
    }.items():
        monkeypatch.setenv(name, value)
    reset_context()
    return cache


def _write_channel(channel: Path, names: tuple[str, ...], builds: int = 1) -> None:
    packages = {}
    for name in names:
        for build in range(builds):
            # The newest candidate must conflict with the pin to exercise version constraints.
            version = "2.0" if builds > 1 and build == builds - 1 else "1.0"
            packages[f"{name}-{version}-{build}.tar.bz2"] = {
                "name": name,
                "version": version,
                "build": str(build),
                "build_number": build,
                "depends": [],
                "subdir": "noarch",
                "noarch": "generic",
                "md5": "0" * 32,
                "sha256": "0" * 64,
                "size": 1,
                "timestamp": 0,
            }
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


def _clear_memory_caches() -> None:
    SubdirData.clear_cached_local_channel_data(exclude_file=False)
    PackageCacheData.clear()


@pytest.mark.benchmark
def test_pinned_request_solve_benchmark(
    benchmark: BenchmarkFixture,
    tmp_path: Path,
    isolated_package_cache: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Include metadata loading, real pin validation, and solving 2,000 candidates."""
    monkeypatch.setenv("CONDA_OFFLINE", "false")
    reset_context()
    names = tuple(f"package-{index:04}" for index in range(10))
    channel = tmp_path / "channel"
    _write_channel(channel, names, builds=200)
    prefix = tmp_path / "prefix"
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True)
    (metadata / "history").touch()
    (metadata / "pinned").write_text("\n".join(f"{name} <2" for name in names))

    def prepare():
        _clear_memory_caches()
        solver = RattlerSolver(
            prefix,
            channels=(Channel(str(channel)),),
            subdirs=(context.subdir, "noarch"),
            specs_to_add=tuple(f"{name} >=1" for name in names),
            command="install",
        )
        return (solver,), {}

    solution = benchmark.pedantic(
        RattlerSolver.solve_final_state,
        setup=prepare,
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )

    assert sorted(
        (record.name, str(record.version), str(record.build)) for record in solution
    ) == [(name, "1.0", "198") for name in names]
    assert all(record.channel.base_url == channel.as_uri() for record in solution)


@pytest.mark.benchmark
@pytest.mark.parametrize("package_count", (100, 563))
def test_empty_package_cache_solve_benchmark(
    benchmark: BenchmarkFixture,
    tmp_path: Path,
    isolated_package_cache: Path,
    package_count: int,
) -> None:
    """Include index construction and Rattler's callbacks for an empty package cache."""
    names = tuple(f"package-{index:04}" for index in range(package_count))
    channel = tmp_path / "channel"
    _write_channel(channel, names)
    specs = tuple(rattler.MatchSpec(name) for name in names)
    subdirs = (context.subdir, "noarch")

    def run():
        index = RattlerIndexHelper(
            channels=(Channel(str(channel)),),
            subdirs=subdirs,
            pkgs_dirs=(str(isolated_package_cache),),
        )
        return asyncio.run(
            rattler.solve(
                sources=index.solve_sources(),
                specs=specs,
                platforms=subdirs,
                strategy="highest",
            )
        )

    solution = benchmark.pedantic(
        run,
        setup=_clear_memory_caches,
        rounds=5,
        iterations=1,
        warmup_rounds=1,
    )

    # Rattler does not promise topological ordering, so compare canonical order.
    assert sorted(
        (record.name.normalized, str(record.version), record.build_number, record.subdir)
        for record in solution
    ) == [(name, "1.0", 0, "noarch") for name in names]
    assert all(str(record.channel).rstrip("/") == channel.as_uri() for record in solution)
    assert not PackageCacheData(isolated_package_cache)._package_cache_records
