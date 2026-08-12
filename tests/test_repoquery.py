# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
import json

from conda.models.channel import Channel

from conda_rattler_solver.index import RattlerIndexHelper

from .utils import conda_subprocess


def test_repoquery():
    p = conda_subprocess("repoquery", "--help")
    assert "whoneeds" in p.stdout
    assert "depends" in p.stdout
    assert "search" in p.stdout

    p = conda_subprocess("repoquery", "depends", "conda", "--json")
    print(p.stdout)
    data = json.loads(p.stdout)
    assert data["result"]["status"] == "OK"
    assert len(data["result"]["pkgs"]) > 0
    python = [p for p in data["result"]["pkgs"] if p["name"] == "python"]
    # Presence is required; uniqueness is not.
    # Duplicate `python` entries can appear when the queried package (e.g. recent
    # conda-forge builds of conda) depends on both unconstrained `python` and a
    # pinned `python X.Y.* *_cpython`. `repoquery depends` resolves each MatchSpec
    # independently, so both (e.g. 3.14 and 3.10) may show up.
    # Upstream: https://github.com/mamba-org/mamba/issues/4346
    # Same carve-out pattern in conda-libmamba-solver tests/test_repoquery.py
    # (https://github.com/conda/conda-libmamba-solver/pull/964).
    assert python


def test_query_search():
    index = RattlerIndexHelper(channels=[Channel("conda-forge")])
    for query in (
        "ca-certificates",
        "ca-certificates =2022.9.24",
        "ca-certificates >=2022.9.24",
        "ca-certificates >2022.9.24",
        "ca-certificates<2022.9.24,>2020",
        "ca-certificates<=2022.9.24,>2020",
        "ca-certificates !=2022.9.24,>2020",
        "ca-certificates=*=*_0",
        "defaults::ca-certificates",
        "defaults::ca-certificates=2022.9.24",
        "defaults::ca-certificates[version='>=2022.9.24']",
        "defaults::ca-certificates[build='*_0']",
    ):
        results = list(index.search(query))
        assert len(results) > 0, query

    assert list(index.search("ca-certificates=*=*_0")) == list(
        index.search("ca-certificates[build='*_0']")
    )
    assert list(index.search("ca-certificates >=2022.9.24")) == list(
        index.search("ca-certificates[version='>=2022.9.24']")
    )
