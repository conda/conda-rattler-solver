# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
import re
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from conda import __version__ as _conda_version
from conda.base.context import context
from conda.models.records import PackageRecord, PrefixRecord

import conda_rattler_solver.utils as utils_module
from conda_rattler_solver.utils import notify_conda_outdated

if TYPE_CHECKING:
    from pathlib import Path


class _FakeIndex:
    """Minimal stand-in for RattlerIndexHelper."""

    def __init__(self, channel_name: str, newer_records: list[PackageRecord]):
        self.channels = [SimpleNamespace(canonical_name=channel_name)]
        self._newer_records = newer_records

    def search(self, spec):
        return self._newer_records


class _FakePrefixData:
    """Stand-in for conda.core.prefix_data.PrefixData"""

    def __init__(self, conda_self_installed: bool, is_frozen: bool = False):
        self._conda_self_installed = conda_self_installed
        self._is_frozen = is_frozen

    def __call__(self, *args, **kwargs) -> _FakePrefixData:
        return self

    def get(self, name, default=None):
        if name == "conda-self" and self._conda_self_installed:
            return PackageRecord(
                name="conda-self",
                version="1.0.0",
                build="pyh_0",
                build_number=0,
                channel="defaults",
                subdir="noarch",
                fn="conda-self-1.0.0-pyh_0.conda",
                md5="1" * 32,
            )
        return default

    def is_frozen(self) -> bool:
        return self._is_frozen


def _write_current_conda_prefix_record(conda_meta_dir, channel_name: str):
    conda_meta_dir.mkdir(parents=True, exist_ok=True)
    record = PrefixRecord(
        name="conda",
        version=_conda_version,
        build="py_0",
        build_number=0,
        channel=channel_name,
        subdir="noarch",
        fn=f"conda-{_conda_version}-py_0.conda",
        md5="0" * 32,
    )
    (conda_meta_dir / f"conda-{_conda_version}-py_0.json").write_text(json.dumps(record.dump()))


@pytest.mark.parametrize(
    "conda_self_installed,frozen,expected_snippet",
    [
        pytest.param(True, True, r"\$ conda self update", id="conda self installed, frozen"),
        pytest.param(True, False, r"\$ conda self update", id="conda self installed, not frozen"),
        pytest.param(
            False,
            True,
            r"\$ conda update -n base -c [\w-]+ conda --override-frozen",
            id="conda self not installed, frozen",
        ),
        pytest.param(
            False,
            False,
            r"\$ conda update -n base -c [\w-]+ conda",
            id="conda self not installed, not frozen",
        ),
    ],
)
def test_notify_conda_outdated_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    conda_self_installed: bool,
    frozen: bool,
    expected_snippet: str,
) -> None:
    """
    Tests the notify conda outdated message.
    - 'conda self update' whenever the 'conda-self' plugin is installed
    - 'conda update ... --override-frozen' when 'conda-self' is absent and the prefix
        is frozen (a plain update is blocked in that case).
    - a plain 'conda update ...' when 'conda-self' is absent and the prefix isn't frozen.
    """

    channel_name = context.channels[0]
    _write_current_conda_prefix_record(tmp_path / "conda-meta", channel_name)

    # Make conda "run from" our fake prefix, which contains the conda-meta record above.
    monkeypatch.setenv("CONDA_NOTIFY_OUTDATED_CONDA", "true")
    monkeypatch.setenv("CONDA_QUIET", "false")
    monkeypatch.setattr(utils_module, "PrefixData", _FakePrefixData(conda_self_installed, frozen))

    newer_record = PackageRecord(
        name="conda",
        version="99.0.0",
        build="py_0",
        build_number=0,
        channel=channel_name,
        subdir="noarch",
        fn="conda-99.0.0-py_0.conda",
        md5="2" * 32,
    )
    index = _FakeIndex(channel_name, [newer_record])

    # Use a target prefix different from context.conda_prefix so the "already updated
    # in this solve" short-circuit doesn't kick in.
    notify_conda_outdated(prefix=str(tmp_path), index=index, final_state=())

    stderr = capsys.readouterr().err
    assert "WARNING: A newer version of conda exists" in stderr
    assert re.search(expected_snippet, stderr)
