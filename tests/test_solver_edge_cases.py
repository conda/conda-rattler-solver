# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conda.core.prefix_data import PrefixData
from conda.exceptions import DryRunExit

from .test_solver import _make_noarch_package

if TYPE_CHECKING:
    from conda.testing.fixtures import CondaCLIFixture, TmpEnvFixture

HERE = Path(__file__).parent
DATA = HERE / "data"


@pytest.mark.parametrize("solver_fixture", ["solver_rattler", "solver_libmamba"])
def test_update_all_does_not_downgrade_installed_packages(
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
    request: pytest.FixtureRequest,
    solver_fixture: str,
) -> None:
    """
    `conda update --all` must not downgrade installed packages in order to upgrade
    others; packages that cannot be upgraded should keep their installed versions.
    libmamba is included as the reference behavior.

    xref: https://github.com/conda/conda-rattler-solver/issues/126
    """
    request.getfixturevalue(solver_fixture)

    # Original environment: top=1.0 -> mid=1.0 -> lib=2.0
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "lib", "2.0")
    _make_noarch_package(channel_b, "mid", "1.0", depends=("lib",))
    _make_noarch_package(channel_b, "top", "1.0", depends=("mid",))

    # The active channel publishes a newer "top" that needs a newer "mid", which in
    # turn only works with an older "lib". Upgrading "top" and "mid" would therefore
    # require downgrading "lib".
    chan_a = tmp_path / "chan-a"
    _make_noarch_package(chan_a, "lib", "1.0")
    _make_noarch_package(chan_a, "lib", "2.0")
    _make_noarch_package(chan_a, "mid", "1.0", depends=("lib",))
    _make_noarch_package(chan_a, "mid", "2.0", depends=("lib<2",))
    _make_noarch_package(chan_a, "top", "1.0", depends=("mid",))
    _make_noarch_package(chan_a, "top", "2.0", depends=("mid>=2",))

    with tmp_env("--override-channels", f"--channel={channel_b}", "lib", "mid", "top") as prefix:
        conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            f"--channel={chan_a}",
            "--all",
            "--yes",
        )

        # Packages may be relinked from the new channel, but nothing can be upgraded
        # without downgrading "lib", so all versions should be left as is.
        PrefixData._cache_.clear()
        packages = {pkg.name: pkg.version for pkg in PrefixData(prefix).iter_records()}
        assert packages["lib"] == "2.0"
        assert packages["mid"] == "1.0"
        assert packages["top"] == "1.0"


@pytest.mark.parametrize("solver_fixture", ["solver_rattler", "solver_libmamba"])
def test_can_update_env_with_python(
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
    request: pytest.FixtureRequest,
    solver_fixture: str,
) -> None:
    """
    Ensure that we can run an update when python is in the environment and the
    channel changes, even if the new channel does not publish versions that are at
    least as new as the installed ones (e.g. moving from defaults to conda-forge).

    libmamba is included as the reference behavior: python keeps its installed
    version, and dependencies the new channel publishes at the same version, but
    with a higher build number, are switched over to the new channel.

    xref: https://github.com/conda/conda-rattler-solver/issues/135
    """
    request.getfixturevalue(solver_fixture)

    # Original environment, standing in for "defaults": python -> openssl=3.5, zlib.
    # pip is needed because conda adds it as a python dependency by default.
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "pip", "25.0", depends=("python",))
    _make_noarch_package(channel_b, "openssl", "3.5.0")
    _make_noarch_package(channel_b, "zlib", "1.3.2")
    _make_noarch_package(channel_b, "python", "3.13.1", depends=("openssl >=3", "zlib"))

    # The new channel, standing in for "conda-forge", has the same python and zlib
    # versions (zlib with a higher build number), but only an older openssl than
    # the one installed.
    chan_a = tmp_path / "chan-a"
    _make_noarch_package(chan_a, "pip", "25.0", depends=("python",))
    _make_noarch_package(chan_a, "openssl", "3.4.0")
    _make_noarch_package(chan_a, "zlib", "1.3.2", build="1", build_number=1)
    _make_noarch_package(chan_a, "python", "3.13.1", depends=("openssl >=3", "zlib"))

    with tmp_env("--override-channels", f"--channel={channel_b}", "python") as prefix:
        out, err, exc = conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            f"--channel={chan_a}",
            "--all",
            "--dry-run",
            "--json",
            raises=DryRunExit,
        )
        data = json.loads(out)
        assert data["success"] is True, err

        linked = {pkg["name"]: pkg for pkg in data["actions"].get("LINK", ())}

        # zlib keeps its version but moves to the new channel's build
        assert linked["zlib"]["version"] == "1.3.2"
        assert linked["zlib"]["build_number"] == 1
        assert linked["zlib"]["channel"].endswith("chan-a")

        # python keeps its installed version
        assert linked.get("python", {"version": "3.13.1"})["version"] == "3.13.1"


@pytest.mark.parametrize("solver_fixture", ["solver_rattler", "solver_libmamba"])
def test_update_all_does_not_downgrade_build_numbers(
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
    request: pytest.FixtureRequest,
    solver_fixture: str,
) -> None:
    """
    `conda update --all` must not "revise" installed packages to a lower build number
    of the same version in order to update others. libmamba is included as the
    reference behavior.

    xref: https://github.com/conda/conda-rattler-solver/issues/126#issuecomment-5871407546
    """
    request.getfixturevalue(solver_fixture)

    # Original environment: gettext and libintl (build number 2) only work with
    # libxml2 <2.15.4; libarchive accepts any libxml2 >=2.15.
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "libxml2", "2.15.3")
    _make_noarch_package(
        channel_b, "libintl", "0.25.1", build="2", build_number=2, depends=("libxml2 <2.15.4",)
    )
    _make_noarch_package(
        channel_b, "gettext", "0.25.1", build="2", build_number=2, depends=("libintl 0.25.1 2",)
    )
    _make_noarch_package(channel_b, "libarchive", "3.8.8", depends=("libxml2 >=2.15",))

    # The active channel publishes everything above, plus a newer libxml2, a new
    # libarchive build that requires it, and gettext/libintl builds with a *lower*
    # build number that allow it. Taking the new libarchive build would therefore
    # require revising gettext and libintl down to build number 0.
    chan_a = tmp_path / "chan-a"
    _make_noarch_package(chan_a, "libxml2", "2.15.3")
    _make_noarch_package(chan_a, "libxml2", "2.15.4")
    _make_noarch_package(
        chan_a, "libintl", "0.25.1", build="2", build_number=2, depends=("libxml2 <2.15.4",)
    )
    _make_noarch_package(chan_a, "libintl", "0.25.1", build="0", depends=("libxml2",))
    _make_noarch_package(
        chan_a, "gettext", "0.25.1", build="2", build_number=2, depends=("libintl 0.25.1 2",)
    )
    _make_noarch_package(chan_a, "gettext", "0.25.1", build="0", depends=("libintl 0.25.1 0",))
    _make_noarch_package(chan_a, "libarchive", "3.8.8", depends=("libxml2 >=2.15",))
    _make_noarch_package(
        chan_a, "libarchive", "3.8.8", build="1", build_number=1, depends=("libxml2 >=2.15.4",)
    )

    with tmp_env(
        "--override-channels", f"--channel={channel_b}", "gettext", "libarchive"
    ) as prefix:
        conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            f"--channel={chan_a}",
            "--all",
            "--yes",
        )

        # Packages may be relinked from the new channel, but no build number should
        # go down, so gettext and libintl stay at build number 2.
        PrefixData._cache_.clear()
        records = {pkg.name: pkg for pkg in PrefixData(prefix).iter_records()}
        assert records["gettext"].build_number == 2
        assert records["libintl"].build_number == 2
        assert records["libxml2"].version == "2.15.3"
