# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Measure shard loading plus solving, and solves that reuse an existing index."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import rattler
from conda.base.context import reset_context

from conda_rattler_solver.index import RattlerIndexHelper

if TYPE_CHECKING:
    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture


URL = "https://benchmark.example.org/channel/linux-64"


def _shards(names: int, versions: int, closure: int):
    entries = []
    for number in range(names):
        name = f"package-{number:04}"
        if versions == 1 and closure == 2:
            depends = ["package-0000 >=1"] if number else []
        else:
            depends = [
                f"package-{child:04} >=1"
                for child in (number * 2 + 1, number * 2 + 2)
                if child < closure
            ]
        for version in range(1, versions + 1):
            record = {
                "name": name,
                "version": str(version),
                "build": "py_0",
                "build_number": 0,
                "subdir": "linux-64",
                "depends": depends,
                "constrains": [],
                "md5": "12" * 16,
                "sha256": "34" * 32,
                "timestamp": 1_700_000_000_000 + version * 1000,
                "size": 123456,
                "license": "BSD-3-Clause",
            }
            entries.append(((f"{name}-{version}-py_0.conda", "packages.conda"), record))
    return {URL: SimpleNamespace(iter_records_v3=lambda: iter(entries))}


def _load_shards(data) -> RattlerIndexHelper:
    index = RattlerIndexHelper.__new__(RattlerIndexHelper)
    index._unlink_on_del = []
    index._index = {}
    index._plan = []
    index._subdirs = ("linux-64",)
    index.in_state = None
    index._index = index._load_repo_info_from_shards(data)
    return index


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "names,versions,closure",
    [
        pytest.param(100, 1, 2, id="100-records-2-solved"),
        pytest.param(5000, 1, 2, id="5000-records-2-solved"),
        pytest.param(1000, 10, 50, id="10000-records-50-solved"),
        pytest.param(1000, 20, 100, id="20000-records-100-solved"),
        pytest.param(100, 10, 100, id="1000-records-100-solved"),
    ],
)
@pytest.mark.parametrize("phase", ("fresh", "warm"))
def test_sharded_solve_benchmark(
    benchmark: BenchmarkFixture,
    monkeypatch: MonkeyPatch,
    names: int,
    versions: int,
    closure: int,
    phase: str,
) -> None:
    """Build raw inputs outside timing and perform no downloads or installation."""
    monkeypatch.setenv("CONDA_USE_ONLY_TAR_BZ2", "false")
    reset_context()
    data = _shards(names, versions, closure)
    requested = names - 1 if versions == 1 and closure == 2 else 0
    solved = (0, requested) if requested else range(closure)
    specs = [f"package-{requested:04} =={versions}"]
    index = _load_shards(data) if phase == "warm" else None

    def run():
        nonlocal index
        if phase == "fresh":
            index = _load_shards(data)
        return asyncio.run(
            rattler.solve_with_sparse_repodata(
                specs=specs,
                sparse_repodata=index.solve_sources(sparse=True),
                package_format_selection=index._package_format,
                virtual_packages=[],
            )
        )

    def cleanup():
        nonlocal index
        if index is not None:
            for info in index._index.values():
                info.repo.close()
            index._index.clear()
            for path in index._unlink_on_del:
                path.unlink(missing_ok=True)
            index._unlink_on_del.clear()
            index = None

    try:
        solution = benchmark.pedantic(
            run,
            teardown=cleanup if phase == "fresh" else None,
            rounds=7,
            iterations=1,
            warmup_rounds=2,
        )
    finally:
        cleanup()

    assert len(solution) == closure
    assert sorted(
        (record.name.normalized, str(record.version), str(record.build), record.url)
        for record in solution
    ) == [
        (name, str(versions), "py_0", f"{URL}/{name}-{versions}-py_0.conda")
        for name in (f"package-{number:04}" for number in solved)
    ]
