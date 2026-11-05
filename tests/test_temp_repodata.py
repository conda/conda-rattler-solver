# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import rattler
from conda._private.shards import ShardLike
from conda.models.records import PackageCacheRecord

from conda_rattler_solver import index as index_module
from conda_rattler_solver.index import RattlerIndexHelper, json_dump
from conda_rattler_solver.utils import empty_repodata_dict

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


def _record(name, version="1.0", subdir="linux-64", depends=(), extension=".conda"):
    record = {
        "name": name,
        "version": version,
        "build": "h123_0",
        "build_number": 0,
        "subdir": subdir,
        "depends": list(depends),
        "constrains": ["optional >=1"],
        "license": "BSD – café",
        "sha256": "a" * 64,
        "md5": "b" * 32,
        "size": 1234,
        "timestamp": 1700000000000,
    }
    if subdir == "noarch":
        record["noarch"] = "generic"
    return f"{name}-{version}-h123_0{extension}", record


def _shards(records):
    repodata_by_url = {}
    for filename, record in records:
        url = f"https://example.invalid/channel/{record['subdir']}"
        repodata = repodata_by_url.setdefault(
            url, empty_repodata_dict(record["subdir"], base_url=url)
        )
        section = "packages" if filename.endswith(".tar.bz2") else "packages.conda"
        repodata[section][filename] = record
    result = {}
    for url, repodata in repodata_by_url.items():
        shard = ShardLike(repodata, url)
        for section in ("packages", "packages.conda"):
            for record in repodata[section].values():
                shard.visit_package(record["name"])
        result[url] = shard
    return result


def _write_cache(cache, records):
    for filename, record in records:
        extracted = cache / f"{record['name']}-{record['version']}-{record['build']}"
        info = extracted / "info"
        info.mkdir(parents=True)
        (info / "index.json").write_text(json.dumps(record))
        (info / "repodata_record.json").write_text(
            json.dumps(
                {
                    **record,
                    "fn": filename,
                    "channel": "https://example.invalid/channel",
                    "url": f"https://example.invalid/channel/{record['subdir']}/{filename}",
                }
            )
        )


@pytest.fixture(params=("shards", "cache"))
def temporary_repos(request, tmp_path):
    records = (
        _record("app", depends=("library >=2",)),
        _record("library", "1.0", "noarch", extension=".tar.bz2"),
        _record("library", "2.0", "noarch", extension=".tar.bz2"),
    )
    index = RattlerIndexHelper(channels=(), subdirs=("linux-64", "noarch"))
    if request.param == "shards":
        repos = list(index._load_repo_info_from_shards(_shards(records)).values())
    else:
        cache = tmp_path / "pkgs"
        _write_cache(cache, records)
        repos = index._load_pkgs_cache((str(cache),))
    try:
        yield repos, records
    finally:
        for info in repos:
            info.repo.close()
        index.__del__()


@pytest.mark.parametrize("temporary_repos", ("cache",), indirect=True)
def test_temporary_repodata_is_compact(temporary_repos):
    repos, _ = temporary_repos
    for info in repos:
        text = Path(info.local_json).read_text()
        assert json.loads(text)["info"]["subdir"] == info.repo.subdir
        assert "\n" not in text
        assert len(text) < len(json_dump(json.loads(text)))


def test_temporary_repodata_preserves_metadata(temporary_repos):
    repos, records = temporary_repos
    loaded = {}
    for info in repos:
        for record in info.repo.load_all_records():
            assert record.subdir == info.repo.subdir
            data = json.loads(record.to_json())
            if "noarch" in data:
                data["noarch"] = "python" if record.noarch.python else "generic"
            if "timestamp" in data:
                data["timestamp"] = int(record.timestamp.timestamp() * 1000)
            loaded[record.file_name] = data
    assert set(loaded) == {filename for filename, _ in records}
    for filename, expected in records:
        assert {key: loaded[filename][key] for key in expected} == expected


@pytest.mark.parametrize(
    "temporary_repos,sparse",
    (("cache", True), ("cache", False), ("shards", True), ("shards", False)),
    ids=("cache-sparse", "cache-gateway", "shards-sparse", "shards-gateway"),
    indirect=("temporary_repos",),
)
def test_temporary_repodata_solves_dependencies(temporary_repos, sparse):
    repos, _ = temporary_repos
    if sparse:
        solution = asyncio.run(
            rattler.solve_with_sparse_repodata(
                specs=["app"], sparse_repodata=[info.repo for info in repos]
            )
        )
    else:
        solution = asyncio.run(
            rattler.solve(specs=["app"], sources=repos, platforms=["linux-64", "noarch"])
        )
    assert {(record.name.normalized, str(record.version)) for record in solution} == {
        ("app", "1.0"),
        ("library", "2.0"),
    }
    for record in solution:
        assert str(record.build) == "h123_0"
        assert record.sha256.hex() == "a" * 64
        assert record.license == "BSD – café"
        info = next(info for info in repos if info.repo.subdir == record.subdir)
        assert record.url == f"{info.full_url}/{record.file_name}"


@pytest.mark.parametrize("section", ("conda", "tar.bz2"))
@pytest.mark.parametrize("sparse", (True, False), ids=("sparse", "gateway"))
def test_temporary_repodata_preserves_v3_extras(section, sparse):
    url = "https://example.invalid/channel/noarch"
    filename, app = _record("v3-app", subdir="noarch", extension=f".{section}")
    app["fn"] = filename
    app["extra_depends"] = {"feature": ["optional >=2"]}
    dependency_filename, dependency = _record("optional", "2.0", "noarch")
    repodata = empty_repodata_dict("noarch", base_url=url)
    repodata["v3"][section][filename.removesuffix(f".{section}")] = app
    repodata["packages.conda"][dependency_filename] = dependency
    shards = ShardLike(repodata, url)
    if "v3-app" not in shards.shards:
        pytest.skip("Conda's ShardLike does not support repodata v3")
    for name in ("v3-app", "optional"):
        shards.visit_package(name)
    index = RattlerIndexHelper(channels=(), subdirs=("noarch",))
    index._index.update(index._load_repo_info_from_shards({url: shards}))
    try:
        info = next(iter(index._index.values()))
        (record,) = info.repo.load_records("v3-app")
        assert record.extra_depends == app["extra_depends"]
        if sparse:
            solution = asyncio.run(
                rattler.solve_with_sparse_repodata(
                    specs=["v3-app[extras=feature]"], sparse_repodata=[info.repo]
                )
            )
        else:
            solution = asyncio.run(
                rattler.solve(
                    specs=["v3-app[extras=feature]"], sources=[info], platforms=["noarch"]
                )
            )
        assert {record.name.normalized for record in solution} == {"v3-app", "optional"}
        solved_app = next(record for record in solution if record.name.normalized == "v3-app")
        assert solved_app.file_name == filename
        assert solved_app.url == f"{url}/{filename}"
    finally:
        index.__del__()


@pytest.mark.benchmark
@pytest.mark.parametrize("record_count", (100, 5000))
@pytest.mark.parametrize("source", ("shards", "cache-records"))
def test_temporary_repodata_benchmark(
    benchmark: BenchmarkFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    record_count: int,
):
    """Load shard or cache records and solve with the resulting sources.

    Shards and cache records are already in memory. Cache-directory scanning is
    excluded so both cases measure record loading and solving.
    """
    records = tuple(
        _record(f"package-{i}", depends=("package-0",) if i else ()) for i in range(record_count)
    )
    shard_data = _shards(records)
    cache = tmp_path / "pkgs"
    cache_records = tuple(
        PackageCacheRecord(
            **record,
            fn=filename,
            channel="https://example.invalid/channel",
            url=f"https://example.invalid/channel/linux-64/{filename}",
            package_tarball_full_path=str(cache / filename),
            extracted_package_dir=str(cache / filename.removesuffix(".conda")),
        )
        for filename, record in records
    )
    if source == "cache-records":
        package_cache = SimpleNamespace(load=lambda: None, values=lambda: cache_records)
        monkeypatch.setattr(index_module, "PackageCacheData", lambda _: package_cache)

    def run():
        index = RattlerIndexHelper(channels=(), subdirs=("linux-64", "noarch"))
        if source == "shards":
            repos = list(index._load_repo_info_from_shards(shard_data).values())
        else:
            repos = index._load_pkgs_cache((str(cache),))
        try:
            solution = asyncio.run(
                rattler.solve_with_sparse_repodata(
                    specs=[f"package-{record_count - 1}"],
                    sparse_repodata=[info.repo for info in repos],
                )
            )
            emitted_bytes = sum(
                Path(info.local_json).stat().st_size for info in repos if info.local_json
            )
            return solution, emitted_bytes
        finally:
            for info in repos:
                info.repo.close()
            index.__del__()

    solution, emitted_bytes = benchmark.pedantic(run, rounds=7, warmup_rounds=2, iterations=1)
    benchmark.extra_info.update(record_count=record_count, emitted_bytes=emitted_bytes)
    if source == "shards":
        assert emitted_bytes == 0
    else:
        assert emitted_bytes > 0
    assert {record.name.normalized for record in solution} == {
        "package-0",
        f"package-{record_count - 1}",
    }
