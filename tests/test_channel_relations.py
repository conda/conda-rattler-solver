# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest
import rattler
from conda.base.context import context
from conda.exceptions import ChannelError
from conda.models.channel import Channel

from conda_rattler_solver import index
from conda_rattler_solver.index import RattlerIndexHelper

if TYPE_CHECKING:
    from pathlib import Path

    from pytest_mock import MockerFixture


@pytest.mark.parametrize("use_shards", (False, True))
def test_shared_resolver_runs_before_acquisition(mocker: MockerFixture, use_shards: bool) -> None:
    heads = [Channel("https://example.org/extension")]
    resolved = (Channel("https://example.org/base"), *heads)
    resolve = mocker.patch.object(index, "resolve_channel_relations", return_value=resolved)
    mocker.patch.object(context, "repodata_use_shards", use_shards)

    def acquire(helper: RattlerIndexHelper) -> dict:
        resolve.assert_called_once_with(
            tuple(heads), ("noarch",), repodata_fn="repodata.json", use_shards=use_shards
        )
        assert helper._urls_from_channels() == (
            "https://example.org/base/noarch",
            "https://example.org/extension/noarch",
        )
        return {}

    mocker.patch.object(RattlerIndexHelper, "_load_channels", autospec=True, side_effect=acquire)
    helper = RattlerIndexHelper(
        channels=iter(heads),
        subdirs=iter(("noarch",)),
        in_state=mocker.Mock(),
        build_repodata_subset=mocker.Mock(),
    )

    assert helper.channels == heads
    assert helper._urls_from_channels() == (
        "https://example.org/base/noarch",
        "https://example.org/extension/noarch",
    )


def test_older_conda_keeps_existing_channels(mocker: MockerFixture) -> None:
    mocker.patch.object(index, "resolve_channel_relations", None)
    mocker.patch.object(RattlerIndexHelper, "_load_channels", return_value={})
    helper = RattlerIndexHelper(channels=["https://example.org/extension"], subdirs=["noarch"])
    assert helper._urls_from_channels() == ("https://example.org/extension/noarch",)
    assert helper._urls_from_channels([]) == ()


def test_relation_failure_prevents_package_acquisition(mocker: MockerFixture) -> None:
    mocker.patch.object(
        index, "resolve_channel_relations", side_effect=ChannelError("relation cycle")
    )
    acquire = mocker.patch.object(RattlerIndexHelper, "_load_channels")
    with pytest.raises(ChannelError, match="relation cycle"):
        RattlerIndexHelper(channels=["https://example.org/extension"])
    acquire.assert_not_called()


@pytest.mark.skipif(index.resolve_channel_relations is None, reason="Needs conda CEP 42 support")
@pytest.mark.parametrize(
    "relation, order", [("base", ("base", "extension")), ("overrides", ("extension", "base"))]
)
def test_native_relations_order_local_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relation: str, order: tuple[str, str]
) -> None:
    monkeypatch.setenv("CONDA_CHANNEL_RELATIONS_MAX_DEPTH", "10")
    for name in ("base", "extension"):
        subdir = tmp_path / name / "noarch"
        subdir.mkdir(parents=True)
        info = {"subdir": "noarch"}
        if name == "extension":
            info["channel_relations"] = {relation: "../base"}
        version = "1.0" if name == "base" else "2.0"
        package = {
            "name": "example",
            "version": version,
            "build": "0",
            "build_number": 0,
            "depends": [],
            "subdir": "noarch",
        }
        (subdir / "repodata.json").write_text(
            json.dumps({"info": info, "packages": {f"example-{version}-0.tar.bz2": package}})
        )

    head = (tmp_path / "extension").as_uri()
    helper = RattlerIndexHelper(channels=[head], subdirs=["noarch"])
    assert tuple(helper._index) == tuple((tmp_path / name / "noarch").as_uri() for name in order)
    assert helper.channels == [Channel(head)]
    solution = asyncio.run(
        rattler.solve_with_sparse_repodata(
            ["example"],
            [info.repo for info in helper._index.values()],
            channel_priority=rattler.ChannelPriority.Strict,
        )
    )
    assert [str(record.version) for record in solution] == ["1.0" if relation == "base" else "2.0"]
