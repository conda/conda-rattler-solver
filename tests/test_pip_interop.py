# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from conda.base.context import context, reset_context
from conda.common.path import get_python_site_packages_short_path
from conda.core.prefix_data import PrefixData
from conda.history import History
from conda.models.enums import PackageType
from conda.models.match_spec import MatchSpec
from conda.models.records import PrefixRecord

from conda_rattler_solver.solver import RattlerSolver

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from conda.testing.fixtures import TmpEnvFixture, TmpRepodataChannelFixture
    from pytest import MonkeyPatch


@pytest.fixture
def pip_prefix(
    tmp_env: TmpEnvFixture,
    tmp_repodata_channel: TmpRepodataChannelFixture,
    temp_package_cache: Path,
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[Path, str, PrefixRecord]]:
    _, channel = tmp_repodata_channel(
        [
            {"name": "python", "version": "3.12.0", "subdir": context.subdir},
            {"name": "unrelated"},
            {"name": "added"},
            {
                "name": "pip-example",
                "version": "1.0",
                "build": "pypi_0",
                "depends": ["python 3.12.*"],
            },
            {"name": "pip-example", "version": "2.0", "depends": ["python 3.12.*"]},
        ]
    )
    monkeypatch.setenv("CONDA_CHANNELS", channel)
    monkeypatch.setenv("CONDA_OFFLINE", "true")
    monkeypatch.setenv("CONDA_PREFIX_DATA_INTEROPERABILITY", "true")
    monkeypatch.setenv("CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY", "false")
    monkeypatch.setenv("CONDA_AUTO_UPDATE_CONDA", "false")
    monkeypatch.setenv("CONDA_AGGRESSIVE_UPDATE_PACKAGES", "")
    monkeypatch.setenv("CONDA_PINNED_PACKAGES", "")
    reset_context()

    with tmp_env() as prefix:
        prefix_data = PrefixData(prefix, interoperability=False)
        for name, version, subdir in (
            ("python", "3.12.0", context.subdir),
            ("unrelated", "1.0", "noarch"),
        ):
            filename = f"{name}-{version}-0.tar.bz2"
            prefix_data.insert(
                PrefixRecord(
                    name=name,
                    version=version,
                    build="0",
                    build_number=0,
                    channel=channel,
                    subdir=subdir,
                    fn=filename,
                    url=f"{channel}/{subdir}/{filename}",
                )
            )
        history = History(prefix)
        history.update()
        history.write_specs(update_specs=("python", "unrelated"))

        site_packages = prefix / get_python_site_packages_short_path("3.12")
        metadata = site_packages / "pip_example-1.0.dist-info"
        metadata.mkdir(parents=True)
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: pip-example\nVersion: 1.0\n"
        )
        (metadata / "RECORD").write_text(
            "pip_example.py,sha256=47DEQpj8HBSa-_TImW-5JCeuQeRkm5NMpJWZG3hSuFU,0\n"
            "pip_example-1.0.dist-info/METADATA,,\n"
        )
        (site_packages / "pip_example.py").write_text("")
        installed = PrefixData(prefix, interoperability=True).reload().get("pip-example")
        assert installed.url is None
        assert installed.fn == "pip_example-1.0.dist-info"
        assert installed.package_type == PackageType.VIRTUAL_PYTHON_WHEEL
        assert any(path.sha256 is not None for path in installed.paths_data.paths)
        assert any(path.sha256 is None for path in installed.paths_data.paths)
        yield prefix, channel, installed


@pytest.mark.parametrize("command", ["install", "remove"])
@pytest.mark.parametrize("pinned", [False, True])
def test_preserve_pip_record(
    pip_prefix: tuple[Path, str, PrefixRecord],
    monkeypatch: MonkeyPatch,
    command: str,
    pinned: bool,
) -> None:
    prefix, channel, installed = pip_prefix
    original = installed.dump()
    if pinned:
        monkeypatch.setenv("CONDA_PINNED_PACKAGES", "pip-example")
        reset_context()
    solver = RattlerSolver(
        prefix,
        channels=(channel,),
        subdirs=context.subdirs,
        specs_to_add=("added",) if command == "install" else (),
        specs_to_remove=("unrelated",) if command == "remove" else (),
        command=command,
    )
    result = {record.name: record for record in solver.solve_final_state()}

    assert result["pip-example"] is installed
    assert result["pip-example"].dump() == original
    assert installed.dump() == original
    assert ("added" in result) == (command == "install")
    assert ("unrelated" in result) == (command != "remove")


@pytest.mark.parametrize("package", ["pip-example", "python"])
def test_remove_pip_record(pip_prefix: tuple[Path, str, PrefixRecord], package: str) -> None:
    prefix, channel, _ = pip_prefix
    solver = RattlerSolver(
        prefix,
        channels=(channel,),
        subdirs=context.subdirs,
        specs_to_remove=(package,),
        command="remove",
    )
    expected = {"python", "unrelated"} if package == "pip-example" else {"unrelated"}
    assert {record.name for record in solver.solve_final_state()} == expected


@pytest.mark.parametrize("version", ["1.0", "2.0"])
def test_replace_pip_record(pip_prefix: tuple[Path, str, PrefixRecord], version: str) -> None:
    prefix, channel, installed = pip_prefix
    original = installed.dump()
    solver = RattlerSolver(
        prefix,
        channels=(channel,),
        subdirs=context.subdirs,
        specs_to_add=(MatchSpec(name="pip-example", version=version, channel=channel),),
        command="install",
    )
    result = {record.name: record for record in solver.solve_final_state()}

    replacement = result["pip-example"]
    assert replacement.version == version
    assert replacement.subdir == "noarch"
    assert replacement.url.startswith(channel)
    assert replacement is not installed
    assert installed.dump() == original
