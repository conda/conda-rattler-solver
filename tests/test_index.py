# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
import rattler
from conda.base.context import context, reset_context
from conda.common.url import path_to_url
from conda.core.subdir_data import SubdirData
from conda.gateways.logging import initialize_logging
from conda.gateways.shards import build_repodata_subset
from conda.models.channel import Channel, MultiChannel
from conda.models.match_spec import MatchSpec

from conda_rattler_solver.index import (
    RattlerIndexHelper,
    _ChannelRepoInfo,
    _is_sharded_repodata_enabled,
    _root_extras,
)
from conda_rattler_solver.state import SolverInputState

if TYPE_CHECKING:
    from os import PathLike

    from conda.testing.fixtures import HttpTestServerFixture, TmpEnvFixture
    from pytest_benchmark.fixture import BenchmarkFixture


initialize_logging()
DATA = Path(__file__).parent / "data"

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


@pytest.mark.parametrize("subdirs", [("noarch",), ("linux-64", "noarch")])
def test_solve_sources_multichannel_grouping(tmp_path: Path, subdirs: tuple[str, ...]):
    """
    Each member of a multichannel (e.g. conda's 'defaults' or condarc's
    'custom_multichannels') becomes its own 'rattler.MultiSource' named after
    the multichannel, so group-named specs match any member while the members
    keep the priority order of the channel list. Standalone channels are
    passed through as-is.
    """
    repo_a, repo_b, standalone = tmp_path / "repo_a", tmp_path / "repo_b", tmp_path / "standalone"
    for repo in (repo_a, repo_b, standalone):
        shutil.copytree(DATA / "mamba_repo", repo)
        for subdir in subdirs:
            repodata = repo / subdir / "repodata.json"
            if not repodata.exists():
                repodata.parent.mkdir(parents=True, exist_ok=True)
                repodata.write_text(json.dumps({"info": {"subdir": subdir}, "packages": {}}))
    multichannel = MultiChannel("mygroup", (Channel(str(repo_a)), Channel(str(repo_b))))

    index = RattlerIndexHelper(channels=(multichannel, Channel(str(standalone))), subdirs=subdirs)

    sources = index.solve_sources()
    assert len(sources) == 2 + len(subdirs)
    for source, repo in ((sources[0], repo_a), (sources[1], repo_b)):
        assert isinstance(source, rattler.MultiSource)
        assert source.name == "mygroup"
        for member, subdir in zip(source.sources, subdirs, strict=True):
            assert isinstance(member, _ChannelRepoInfo)
            assert member.noauth_url == f"{path_to_url(str(repo))}/{subdir}"
    assert all(isinstance(source, _ChannelRepoInfo) for source in sources[2:])

    sparse = index.solve_sources(sparse=True)
    assert len(sparse) == 2 + len(subdirs)
    for source in sparse[:2]:
        assert isinstance(source, rattler.MultiSource)
        assert source.name == "mygroup"
        assert len(source.sources) == len(subdirs)
        assert all(isinstance(member, rattler.SparseRepoData) for member in source.sources)
    assert all(isinstance(source, rattler.SparseRepoData) for source in sparse[2:])


def test_solve_sources_empty_multichannel(tmp_path: Path):
    "Multichannels without members (e.g. 'local' without conda-build paths) are ignored."
    standalone = tmp_path / "standalone"
    shutil.copytree(DATA / "mamba_repo", standalone)

    index = RattlerIndexHelper(
        channels=(MultiChannel("empty-group", ()), Channel(str(standalone))), subdirs=("noarch",)
    )

    sources = index.solve_sources()
    assert len(sources) == 1
    assert isinstance(sources[0], _ChannelRepoInfo)
    assert index.solve_sources(sparse=True) == [sources[0].repo]


def test_solve_sources_multichannel_run_separation(tmp_path: Path):
    """
    A multichannel whose members are separated by other channels forms a
    separate group at each run, so the repodata order follows the channel list
    instead of pulling the whole multichannel to the first member's position.
    """
    repo_x, repo_y, standalone = tmp_path / "repo_x", tmp_path / "repo_y", tmp_path / "standalone"
    for repo in (repo_x, repo_y, standalone):
        shutil.copytree(DATA / "mamba_repo", repo)

    index = RattlerIndexHelper(
        channels=(
            MultiChannel("mygroup", (Channel(str(repo_x)),)),
            Channel(str(standalone)),
            MultiChannel("mygroup", (Channel(str(repo_y)),)),
        ),
        subdirs=("noarch",),
    )

    sources = index.solve_sources(sparse=True)
    assert len(sources) == 3
    first, middle, last = sources
    assert isinstance(first, rattler.MultiSource)
    assert first.name == "mygroup"
    assert len(first.sources) == 1
    assert isinstance(middle, rattler.SparseRepoData)
    assert isinstance(last, rattler.MultiSource)
    assert last.name == "mygroup"
    assert len(last.sources) == 1
    # each run holds its own member's repodata
    (first_record,) = first.sources[0].load_all_records()
    (last_record,) = last.sources[0].load_all_records()
    assert str(first_record.channel).rstrip("/") == path_to_url(str(repo_x))
    assert str(last_record.channel).rstrip("/") == path_to_url(str(repo_y))


def test_channel_plan_first_listing_wins(tmp_path: Path):
    "The first listing of a channel provides its URLs; later re-listings are skipped."
    repo = tmp_path / "repo"
    shutil.copytree(DATA / "mamba_repo", repo)
    index = RattlerIndexHelper(channels=[str(repo)], subdirs=("noarch",))
    plan = index._plan_channels(
        channels=(
            Channel("https://example.com/conda"),
            Channel("conda-forge"),
            Channel("https://example.com/t/some-token/conda"),
            Channel("https://user:pass@example.com/conda"),
        )
    )
    assert [(name, list(member_urls)) for name, member_urls in plan] == [
        (None, ["https://example.com/conda/noarch"]),
        (None, ["https://conda.anaconda.org/conda-forge/noarch"]),
    ]
    fetch_urls = [fetch_url for _, member_urls in plan for fetch_url in member_urls.values()]
    assert fetch_urls == [
        "https://example.com/conda/noarch",
        "https://conda.anaconda.org/conda-forge/noarch",
    ]


def test_channel_plan_authenticated_first(tmp_path: Path):
    "The first listing provides the credentials when it has any; re-listings are skipped."
    repo = tmp_path / "repo"
    shutil.copytree(DATA / "mamba_repo", repo)
    index = RattlerIndexHelper(channels=[str(repo)], subdirs=("noarch",))
    plan = index._plan_channels(
        channels=(
            Channel("https://example.com/t/some-token/conda"),
            Channel("https://example.com/conda"),
        )
    )
    fetch_urls = [fetch_url for _, member_urls in plan for fetch_url in member_urls.values()]
    assert fetch_urls == ["https://example.com/conda/t/some-token/noarch"]


@pytest.mark.parametrize("use_cdn", [False, True], ids=["channel-download", "cdn-download"])
def test_expanded_search_preserves_authenticated_downloads(http_test_server, monkeypatch, use_cdn):
    noarch = http_test_server.directory / "noarch"
    noarch.mkdir()
    info = {"subdir": "noarch"}
    if use_cdn:
        info["base_url"] = "https://cdn.example.test/packages/noarch/"
    filename = "demo-1.0-0.tar.bz2"
    (noarch / "repodata.json").write_text(
        json.dumps(
            {
                "info": info,
                "repodata_version": 2,
                "packages": {
                    filename: {
                        "name": "demo",
                        "version": "1.0",
                        "build": "0",
                        "build_number": 0,
                        "depends": [],
                        "subdir": "noarch",
                    }
                },
                "packages.conda": {},
            }
        )
    )
    authenticated = http_test_server.url.replace("http://", "http://user:password@")
    index = RattlerIndexHelper(channels=[Channel(authenticated)], subdirs=("noarch",))
    expanded = index._index
    monkeypatch.setattr(index, "_index", {})
    monkeypatch.setattr(index, "_get_root_package_from_shard", lambda names: expanded)

    (record,) = index.search("demo", search_expanded_index=True)

    assert record.channel.url(with_credentials=True) == f"{authenticated}/noarch"
    download_base = info["base_url"] if use_cdn else f"{authenticated}/noarch/"
    assert record.url == f"{download_base}{filename}"


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


@pytest.mark.parametrize(
    "requested,history,prune,expected",
    [
        pytest.param(["httpx", "numpy"], [], False, {}, id="no-extras"),
        pytest.param(
            ["httpx[extras=cli]", "numpy"], [], False, {"httpx": ["cli"]}, id="requested"
        ),
        pytest.param(
            ['httpx[extras="cli,http2"]', "requests[extras=socks]"],
            [],
            False,
            {"httpx": ["cli", "http2"], "requests": ["socks"]},
            id="several-packages-and-extras",
        ),
        pytest.param([], ["httpx[extras=cli]"], False, {"httpx": ["cli"]}, id="history-only"),
        # the solver uses the requested spec instead of the history one, so it wins
        pytest.param(
            ["httpx[extras=http2]"],
            ["httpx[extras=cli]"],
            False,
            {"httpx": ["http2"]},
            id="requested-overrides-history",
        ),
        pytest.param(["httpx"], ["httpx[extras=cli]"], False, {}, id="requested-without-extras"),
        pytest.param(
            ["numpy"],
            ["httpx[extras=cli]"],
            False,
            {"httpx": ["cli"]},
            id="history-kept-for-other-packages",
        ),
        # pruning acts as if there were no history
        pytest.param(["numpy"], ["httpx[extras=cli]"], True, {}, id="prune-ignores-history"),
        pytest.param(
            ["httpx[extras=http2]"],
            ["httpx[extras=cli]", "requests[extras=socks]"],
            True,
            {"httpx": ["http2"]},
            id="prune-keeps-requested",
        ),
    ],
)
def test_root_extras(requested, history, prune, expected):
    # minimal stand-in for SolverInputState with only what `_root_extras` reads
    state = SimpleNamespace(
        requested={s.name: s for s in map(MatchSpec, requested)},
        history={s.name: s for s in map(MatchSpec, history)},
        prune=prune,
    )
    assert _root_extras(state) == expected
