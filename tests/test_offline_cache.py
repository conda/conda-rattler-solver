# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from conda.base.context import context, reset_context
from conda.core.package_cache_data import PackageCacheData
from conda.core.prefix_data import PrefixData
from conda_package_handling.api import create

from conda_rattler_solver.solver import RattlerSolver

from .test_index import _make_cache_record

if TYPE_CHECKING:
    from pathlib import Path

    from conda.testing.fixtures import CondaCLIFixture
    from pytest import MonkeyPatch


@pytest.mark.parametrize("operation", ["create", "update"])
def test_offline_cache_transaction(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    conda_cli: CondaCLIFixture,
    operation: str,
) -> None:
    """Resolve and install a native package with a cached noarch dependency."""
    cache = tmp_path / "pkgs"
    prefix = tmp_path / "env"
    channel = tmp_path / "empty-channel"
    native_subdir = context.subdir
    for subdir in (native_subdir, "noarch"):
        directory = channel / subdir
        directory.mkdir(parents=True)
        (directory / "repodata.json").write_text(
            json.dumps({"info": {"subdir": subdir}, "packages": {}, "packages.conda": {}})
        )

    versions = ("1.0", "2.0") if operation == "update" else ("1.0",)
    for version in versions:
        for name, subdir in (("cache-dependency", "noarch"), ("cache-app", native_subdir)):
            extracted = _make_cache_record(cache, name, subdir, version=version)
            for filename in ("index.json", "repodata_record.json"):
                path = extracted / "info" / filename
                record = json.loads(path.read_text())
                if name == "cache-app":
                    record["depends"] = [f"cache-dependency =={version}"]
                path.write_text(json.dumps(record))
            (extracted / "info" / "files").write_text("")
            (extracted / "info" / "paths.json").write_text(
                json.dumps({"paths_version": 1, "paths": []})
            )
            create(
                str(extracted),
                ["info/index.json", "info/files", "info/paths.json"],
                f"{extracted.name}.conda",
                out_folder=str(cache),
            )

    monkeypatch.setenv("CONDA_PKGS_DIRS", str(cache))
    monkeypatch.setenv("CONDA_OFFLINE", "true")
    monkeypatch.setenv("CONDA_NOTIFY_OUTDATED_CONDA", "false")
    monkeypatch.setenv("CONDA_REPODATA_USE_SHARDS", "false")
    monkeypatch.setenv("CONDA_REPODATA_USE_ZST", "false")
    reset_context()
    PackageCacheData.clear()

    conda_cli(
        "create",
        f"--prefix={prefix}",
        "--solver=rattler",
        "--offline",
        "--override-channels",
        f"--channel={channel}",
        "--no-default-packages",
        "--yes",
        "cache-app=1.0",
    )
    expected_version = "1.0"
    if operation == "update":
        conda_cli(
            "update",
            f"--prefix={prefix}",
            "--solver=rattler",
            "--offline",
            "--override-channels",
            f"--channel={channel}",
            "--yes",
            "cache-app",
        )
        expected_version = "2.0"

    installed = {record.name: record for record in PrefixData(prefix).reload().iter_records()}
    assert set(installed) == {"cache-app", "cache-dependency"}
    assert all(record.version == expected_version for record in installed.values())
    assert installed["cache-app"].depends == (f"cache-dependency =={expected_version}",)
    assert installed["cache-dependency"].subdir == "noarch"
    assert installed["cache-app"].subdir == native_subdir

    solver = RattlerSolver(
        prefix=prefix,
        channels=[str(channel)],
        subdirs=(native_subdir, "noarch"),
        specs_to_add=[f"cache-app={expected_version}"],
        command="install",
    )
    unlink, link = solver.solve_for_diff()
    assert not unlink
    assert not link
