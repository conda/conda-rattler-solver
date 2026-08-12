# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conda.base.context import context, reset_context
from conda.core.exclude_newer import ExcludeNewerPolicy
from conda.core.subdir_data import SubdirData
from conda.gateways.logging import initialize_logging
from conda.gateways.shards import build_repodata_subset
from conda.models.channel import Channel

from conda_rattler_solver.index import RattlerIndexHelper, _is_sharded_repodata_enabled
from conda_rattler_solver.state import SolverInputState

if TYPE_CHECKING:
    from os import PathLike

    from conda.testing.fixtures import HttpTestServerFixture, TmpEnvFixture
    from pytest_benchmark.fixture import BenchmarkFixture


initialize_logging()
DATA = Path(__file__).parent / "data"
NOW = 1_700_000_000.0
DAY = 86400

CONDA_FORGE_WITH_SHARDS = "conda-forge"


def test_given_channels(monkeypatch: pytest.MonkeyPatch, tmp_path: PathLike):
    monkeypatch.setenv("CONDA_PKGS_DIRS", str(tmp_path))
    reset_context()
    rattler_index = RattlerIndexHelper.from_platform_aware_channel(
        channel=Channel("conda-test/noarch")
    )
    assert len(rattler_index._index) == 1

    conda_index = SubdirData(Channel("conda-test/noarch"))
    conda_index.load()

    assert rattler_index.n_packages() == len(tuple(conda_index.iter_records()))


@pytest.mark.parametrize(
    "only_tar_bz2",
    (
        pytest.param("1", id="CONDA_USE_ONLY_TAR_BZ2=true"),
        pytest.param("", id="CONDA_USE_ONLY_TAR_BZ2=false"),
    ),
)
def test_defaults_use_only_tar_bz2(monkeypatch: pytest.MonkeyPatch, only_tar_bz2: str):
    """
    Defaults is particular in the sense that it offers both .tar.bz2 and .conda for LOTS
    of packages. SubdirData ignores .tar.bz2 entries if they have a .conda counterpart.
    So if we count all the packages in each implementation, rattler's has way more.
    To remain accurate, we test this with `use_only_tar_bz2`:
        - When true, we only count .tar.bz2
        - When false, we only count .conda
    """
    monkeypatch.setenv("CONDA_USE_ONLY_TAR_BZ2", only_tar_bz2)
    reset_context()
    main_noarch_channel = Channel.from_url("https://repo.anaconda.com/pkgs/main/noarch")
    rattler_index = RattlerIndexHelper.from_platform_aware_channel(main_noarch_channel)
    assert len(rattler_index._index) == 1

    rattler_dot_conda_total = rattler_index.n_packages(
        filter_=lambda pkg: pkg.url.endswith(".conda")
    )
    rattler_tar_bz2_total = rattler_index.n_packages(
        filter_=lambda pkg: pkg.url.endswith(".tar.bz2")
    )

    conda_dot_conda_total = 0
    conda_tar_bz2_total = 0
    for channel_url in main_noarch_channel.urls(subdirs=("noarch",)):
        conda_index = SubdirData(Channel(channel_url))
        conda_index.load()
        for pkg in conda_index.iter_records():
            if pkg["url"].endswith(".conda"):
                conda_dot_conda_total += 1
            elif pkg["url"].endswith(".tar.bz2"):
                conda_tar_bz2_total += 1
            else:
                raise RuntimeError(f"Unrecognized package URL: {pkg['url']}")

    if only_tar_bz2:
        assert conda_tar_bz2_total == rattler_tar_bz2_total
        assert rattler_dot_conda_total == conda_dot_conda_total == 0
    else:
        assert conda_dot_conda_total == rattler_dot_conda_total
        assert conda_tar_bz2_total == rattler_tar_bz2_total


def test_reload_channels(tmp_path: Path):
    (tmp_path / "noarch").mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "mamba_repo" / "noarch" / "repodata.json", tmp_path / "noarch")
    initial_repodata = (tmp_path / "noarch" / "repodata.json").read_text()
    index = RattlerIndexHelper(channels=[Channel(str(tmp_path))])
    initial_count = index.n_packages()
    SubdirData._cache_.clear()

    data = json.loads(initial_repodata)
    package = data["packages"]["test-package-0.1-0.tar.bz2"]
    data["packages"]["test-package-copy-0.1-0.tar.bz2"] = {**package, "name": "test-package-copy"}
    modified_repodata = json.dumps(data)
    (tmp_path / "noarch" / "repodata.json").write_text(modified_repodata)

    assert initial_repodata != modified_repodata
    # TODO: Remove this sleep after addressing
    # https://github.com/conda/conda/issues/13783
    time.sleep(1)
    index.reload_channel(Channel(str(tmp_path)))
    assert index.n_packages() == initial_count + 1


def test_exclude_newer_python_filter_disabled_for_global_only_policy():
    index = object.__new__(RattlerIndexHelper)
    index._unlink_on_del = []
    index._index = {}
    index.exclude_newer_policy = ExcludeNewerPolicy(global_cutoff=1234.56)
    index._use_python_exclude_newer_filter = False

    path = Path("repodata.json")
    assert index._filtered_json_path("https://example.test/conda/linux-64", path) == path


def test_exclude_newer_record_filter_honors_package_and_channel_overrides():
    index = object.__new__(RattlerIndexHelper)
    index._unlink_on_del = []
    index._index = {}
    index.exclude_newer_policy = ExcludeNewerPolicy.from_values(
        "1d",
        {"openssl": "false", "numpy": "1d"},
        channel_settings=({"channel": "https://example.test/conda", "exclude_newer": "3d"},),
        now=NOW,
    )

    def allowed(name: str, channel_url: str, timestamp: float) -> bool:
        filename = f"{name}-1.0-0.tar.bz2"
        package_url = f"{channel_url}/{filename}"
        return index._record_allowed(
            {"name": name, "timestamp": timestamp},
            filename,
            channel_url,
            package_url,
        )

    assert allowed("openssl", "https://example.test/conda/linux-64", NOW - 60)
    assert allowed("numpy", "https://example.test/conda/linux-64", NOW - 2 * DAY)
    assert not allowed("scipy", "https://example.test/conda/linux-64", NOW - 2 * DAY)
    assert allowed("scipy", "https://other.example.test/conda/linux-64", NOW - 2 * DAY)


def test_exclude_newer_filter_repodata_keeps_unknown_timestamps(tmp_path):
    index = object.__new__(RattlerIndexHelper)
    index._unlink_on_del = []
    index._index = {}
    index.exclude_newer_policy = ExcludeNewerPolicy.from_values(
        "",
        {},
        channel_settings=({"channel": "https://example.test/conda", "exclude_newer": "1d"},),
        now=NOW,
    )
    index._use_python_exclude_newer_filter = True
    repodata = {
        "packages": {
            "old-1.0-0.tar.bz2": {"name": "old", "timestamp": NOW - 2 * DAY},
            "new-1.0-0.tar.bz2": {"name": "new", "timestamp": NOW - 60},
            "unknown-1.0-0.tar.bz2": {"name": "unknown"},
        },
        "packages.conda": {},
    }

    json_path = tmp_path / "repodata.json"
    json_path.write_text(json.dumps(repodata))
    filtered_path = index._filtered_json_path(
        "https://example.test/conda/linux-64",
        json_path,
    )
    filtered = json.loads(filtered_path.read_text())

    assert set(filtered["packages"]) == {
        "old-1.0-0.tar.bz2",
        "unknown-1.0-0.tar.bz2",
    }


@pytest.mark.parametrize(
    "load_type,requested",
    [
        ("shard", ("python",)),
        ("shard", ("django", "celery")),
        ("shard", ("vaex",)),
        ("repodata", ("vaex",)),
        ("main", ()),
    ],
    ids=["shard-small", "shard-medium", "shard-large", "noshard", "main"],
)
def test_load_channel_repo_info_shards(
    load_type: str,
    requested: tuple[str, ...],
    tmp_env: TmpEnvFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    """Exercise sharded vs classic repodata loading (networked).

    Shard cases must return a non-empty index with fewer packages than the full
    repodata.json for the same channel, confirming the subset path was taken.
    The noshard and main cases use full repodata.json and serve as the baseline.
    """
    load_channel = "defaults" if load_type == "main" else CONDA_FORGE_WITH_SHARDS

    monkeypatch.setattr(context, "repodata_use_shards", load_type == "shard")
    assert _is_sharded_repodata_enabled() == (load_type == "shard")

    if load_type == "shard":
        _build_repodata_subset = build_repodata_subset
    else:
        _build_repodata_subset = None

    with tmp_env("xz", "--solver=rattler") as prefix:
        in_state = SolverInputState(prefix, requested=requested)
        index_helper = RattlerIndexHelper(
            channels=[Channel(f"{load_channel}/{context.subdir}")],
            subdirs=(
                "noarch",
                context.subdir,
            ),
            in_state=in_state,
            build_repodata_subset=_build_repodata_subset,
        )

        assert len(index_helper._index) > 0

        if load_type == "shard":
            # Shards deliver a dependency-closure subset — must be smaller than full repodata.
            # Build the full-repodata baseline for the same channel to compare against.
            full_index = RattlerIndexHelper(
                channels=[Channel(f"{load_channel}/{context.subdir}")],
                subdirs=("noarch", context.subdir),
                in_state=in_state,
                build_repodata_subset=None,
            )
            shard_package_count = index_helper.n_packages()
            full_package_count = full_index.n_packages()
            assert shard_package_count > 0, "Shard index must contain at least one package"
            assert shard_package_count < full_package_count, (
                f"Shard index ({shard_package_count} packages) should be a strict subset of "
                f"full repodata ({full_package_count} packages)"
            )


def test_search_non_sharded_channels(tmp_path: Path):
    (tmp_path / "noarch").mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "mamba_repo" / "noarch" / "repodata.json", tmp_path / "noarch")
    index = RattlerIndexHelper(channels=[Channel(str(tmp_path))])
    results = list(index.search("test-package"))
    assert len(results) == 1
    assert results[0].name == "test-package"


@pytest.mark.parametrize(
    "http_test_server",
    [DATA / "sharded_repo"],
    indirect=True,
)
def test_search_sharded_channels(tmp_path: Path, http_test_server: HttpTestServerFixture):
    """
    This test ensures that searching the index works for a sharded channel. When
    `search_expanded_index` is True, the search should be sure to build the
    repodata subset of the requested package to include it in the search results.
    Further, the search should not effect the internal index state.
    """
    url = http_test_server.url
    index = RattlerIndexHelper(
        channels=[Channel(url)],
        build_repodata_subset=build_repodata_subset,
        in_state=SolverInputState(tmp_path),
    )

    results = list(index.search("foo", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "foo"

    results = list(index.search("foo", search_expanded_index=False))
    assert len(results) == 0

    results = list(index.search("bar", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "bar"

    results = list(index.search("idontexist", search_expanded_index=True))
    assert len(results) == 0

    results = list(result for result in index.search("bar>2", search_expanded_index=True))
    assert len(results) == 0

    results = list(index.search("bar==1", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "bar"


@pytest.mark.parametrize(
    "http_test_server",
    [DATA / "sharded_repo"],
    indirect=True,
)
def test_search_sharded_channels_with_requested_packages(
    tmp_path: Path, http_test_server: HttpTestServerFixture
):
    """
    This test ensures that if a package is in the set of requested packages,
    it should not require loading the expanded index to find it.
    """
    url = http_test_server.url
    index = RattlerIndexHelper(
        channels=[Channel(url)],
        build_repodata_subset=build_repodata_subset,
        in_state=SolverInputState(tmp_path, requested=["foo"]),
    )

    results = list(index.search("foo", search_expanded_index=False))
    assert len(results) == 1
    assert results[0].name == "foo"

    results = list(index.search("bar", search_expanded_index=False))
    assert len(results) == 1
    assert results[0].name == "bar"

    results = list(index.search("idontexist", search_expanded_index=False))
    assert len(results) == 0

    results = list(index.search("idontexist", search_expanded_index=True))
    assert len(results) == 0


@pytest.mark.parametrize(
    "http_test_server",
    [DATA / "sharded_repo"],
    indirect=True,
)
def test_search_combo_sharded_channels(tmp_path: Path, http_test_server: HttpTestServerFixture):
    """
    This test ensures that searching the index works for a combination of sharded
    and non-sharded channels.
    """
    url = http_test_server.url
    (tmp_path / "noarch").mkdir(parents=True, exist_ok=True)
    shutil.copy(DATA / "mamba_repo" / "noarch" / "repodata.json", tmp_path / "noarch")

    index = RattlerIndexHelper(
        channels=[Channel(url), Channel(str(tmp_path))],
        build_repodata_subset=build_repodata_subset,
        in_state=SolverInputState(tmp_path),
    )

    results = list(index.search("foo", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "foo"

    results = list(index.search("foo", search_expanded_index=False))
    assert len(results) == 0

    results = list(index.search("bar", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "bar"

    results = list(index.search("test-package", search_expanded_index=True))
    assert len(results) == 1
    assert results[0].name == "test-package"


@pytest.mark.benchmark
@pytest.mark.parametrize("query", ["foo", "bar", "bar>2", "idontexist"])
@pytest.mark.parametrize("expand_search", [True, False])
@pytest.mark.parametrize(
    "http_test_server",
    [DATA / "sharded_repo"],
    indirect=True,
)
def test_query_search_benchmark(
    benchmark: BenchmarkFixture,
    tmp_path: Path,
    query: str,
    expand_search: bool,
    http_test_server: HttpTestServerFixture,
):
    """
    Benchmark searching for a package that does not exist in the loaded part of the index.

    Should observe that setting `search_expanded_index` to `True` will be much slower
    than when it is set to `False`. From the related unit tests, we can confirm that
    without using the `search_expanded_index` option, these searches will not find the
    requested package.
    """
    url = http_test_server.url
    index = RattlerIndexHelper(
        channels=[Channel(url)],
        build_repodata_subset=build_repodata_subset,
        in_state=SolverInputState(tmp_path),
    )

    def run():
        list(index.search(query, search_expanded_index=expand_search))

    benchmark(run)


@pytest.mark.benchmark
@pytest.mark.parametrize("query", ["foo", "bar", "bar>2", "idontexist"])
@pytest.mark.parametrize("expand_search", [True, False])
@pytest.mark.parametrize(
    "http_test_server",
    [DATA / "sharded_repo"],
    indirect=True,
)
def test_query_search_requested_packages_benchmark(
    benchmark: BenchmarkFixture,
    tmp_path: Path,
    query: str,
    expand_search: bool,
    http_test_server: HttpTestServerFixture,
):
    """
    Benchmark searching for packages with the context of a package already being requested.

    Should observe that searching the index for a package that has been requested as
    part of the input state should be about the same speed for searching with the
    `search_expanded_index` set to `True` or `False`.
    """
    url = http_test_server.url
    index = RattlerIndexHelper(
        channels=[Channel(url)],
        build_repodata_subset=build_repodata_subset,
        in_state=SolverInputState(tmp_path, requested=["foo"]),
    )

    def run():
        list(index.search(query, search_expanded_index=expand_search))

    benchmark(run)
