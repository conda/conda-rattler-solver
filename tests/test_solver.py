# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import bz2
import io
import json
import os
import shutil
import sys
import tarfile
from itertools import chain, permutations, repeat
from pathlib import Path
from subprocess import run
from textwrap import dedent
from typing import TYPE_CHECKING

import pytest
from conda._private.shards import ShardLike
from conda.base.constants import UpdateModifier
from conda.base.context import context, reset_context
from conda.common.compat import on_linux, on_mac, on_win
from conda.core.prefix_data import PrefixData
from conda.exceptions import (
    DryRunExit,
    PackagesNotFoundError,
    SpecsConfigurationConflictError,
    UnsatisfiableError,
)
from conda.models.channel import Channel
from conda.models.match_spec import MatchSpec
from conda.models.records import PrefixRecord
from conda.testing.integration import package_is_installed
from conda.testing.solver_helpers import SolverTests
from rattler.exceptions import SolverError as RattlerSolverError

from conda_rattler_solver.exceptions import RattlerUnsatisfiableError
from conda_rattler_solver.index import RattlerIndexHelper
from conda_rattler_solver.solver import RattlerSolver as Solver
from conda_rattler_solver.state import SolverInputState, SolverOutputState

from .utils import conda_subprocess

if TYPE_CHECKING:
    from os import PathLike

    from conda.testing.fixtures import CondaCLIFixture, PipCLIFixture, TmpEnvFixture
    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture

HERE = Path(__file__).parent
DATA = HERE / "data"


def _make_noarch_package(
    channel_dir: Path,
    name: str,
    version: str,
    build: str = "0",
    depends: tuple[str, ...] = (),
) -> None:
    """
    Write a minimal (content-free) noarch package tarball into ``channel_dir / "noarch"``,
    for use as a throwaway local channel in tests that only care about dependency resolution.
    """
    noarch_dir = channel_dir / "noarch"
    noarch_dir.mkdir(parents=True, exist_ok=True)
    fn = f"{name}-{version}-{build}.tar.bz2"
    index_json = {
        "arch": None,
        "build": build,
        "build_number": 0,
        "depends": list(depends),
        "name": name,
        "noarch": "generic",
        "platform": None,
        "subdir": "noarch",
        "timestamp": 1700000000000,
        "version": version,
    }
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for relpath, payload in (
            ("info/index.json", json.dumps(index_json).encode()),
            ("info/paths.json", json.dumps({"paths": [], "paths_version": 1}).encode()),
        ):
            info = tarfile.TarInfo(relpath)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    (noarch_dir / fn).write_bytes(bz2.compress(buf.getvalue()))

    repodata_path = noarch_dir / "repodata.json"
    repodata = (
        json.loads(repodata_path.read_text())
        if repodata_path.is_file()
        else {"info": {"subdir": "noarch"}, "packages": {}, "packages.conda": {}}
    )
    repodata["packages"][fn] = index_json
    repodata_path.write_text(json.dumps(repodata))


class TestRattlerSolver(SolverTests):
    @property
    def solver_class(self) -> type[Solver]:
        return Solver

    @property
    def tests_to_skip(self):
        return {
            "conda-rattler-solver does not support features": [
                "test_iopro_mkl",
                "test_iopro_nomkl",
                "test_mkl",
                "test_accelerate",
                "test_scipy_mkl",
                "test_pseudo_boolean",
                "test_no_features",
                "test_surplus_features_1",
                "test_surplus_features_2",
                "test_remove",
                # this one below only fails reliably on windows;
                # it passes Linux on CI, but not locally?
                "test_unintentional_feature_downgrade",
            ],
        }


def test_python_downgrade_reinstalls_noarch_packages(
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
    pip_cli: PipCLIFixture,
) -> None:
    """
    Reported in https://github.com/conda/conda/issues/11346

    See also test_create::test_noarch_python_package_reinstall_on_pyver_change
    in conda/conda test suite. Note that we use conda-forge here deliberately;
    defaults at the time of writing (March 2022) packages pip as a non-noarch
    build, which means it has a different name across Python versions. conda-forge
    uses noarch here, so the package is the same across Python versions. Probably
    why upstream didn't catch this error before.
    """
    with tmp_env(
        "--override-channels",
        "--channel=conda-forge",
        "--solver=rattler",
        "pip",
        "python=3.11",
    ) as prefix:
        assert PrefixData(prefix).get("python").version.startswith("3.11")
        pip_cli("--version", prefix=prefix)

        conda_cli(
            "install",
            f"--prefix={prefix}",
            "--solver=rattler",
            "--override-channels",
            "--channel=conda-forge",
            "python=3.10",
            "--yes",
        )
        PrefixData._cache_.clear()
        assert PrefixData(prefix).get("python").version.startswith("3.10")
        pip_cli("--version", prefix=prefix)


@pytest.mark.xfail(
    reason="multichannels not fully implemented yet: https://github.com/conda/rattler/issues/1327",
    strict=True,
)
def test_defaults_specs_work(conda_cli: CondaCLIFixture) -> None:
    """
    See https://github.com/conda/conda-libmamba-solver/issues/173

    defaults is secretly (main, r and msys2), and repos are built using those
    actual channels. Multichannels are not present in rattler so far.
    """
    out, err, rc = conda_cli(
        "create",
        "--dry-run",
        "--json",
        "--solver=rattler",
        "--override-channels",
        "--channel=conda-forge",
        "python=3.10",
        "defaults::libarchive",
        raises=DryRunExit,
    )
    data = json.loads(out)
    assert data.get("success") is True
    for link in data["actions"]["LINK"]:
        if link["name"] == "libarchive":
            assert link["channel"] in ("defaults", "pkgs/main")
            break
    else:
        raise AssertionError("libarchive not found in LINK actions")


def test_determinism(tmpdir):
    "Based on https://github.com/conda/conda-libmamba-solver/issues/75"
    env = os.environ.copy()
    env.pop("PYTHONHASHSEED", None)
    env["CONDA_PKGS_DIRS"] = str(tmpdir / "pkgs")
    installed_bokeh_versions = []
    common_args = (
        sys.executable,
        "-mconda",
        "create",
        "--name=unused",
        "--dry-run",
        "--yes",
        "--json",
        "--solver=rattler",
        "--channel=conda-forge",
        "--override-channels",
    )
    pkgs = ("python=3.8", "bokeh", "hvplot")
    # Two things being tested in the same loop:
    # - Repeated attempts of the same input should give the same result
    # - Input order (from the user side) should not matter, and should give the same result
    for i, pkg_list in enumerate(chain(repeat(pkgs, 10), permutations(pkgs, len(pkgs)))):
        offline = ("--offline",) if i else ()
        process = run([*common_args, *offline, *pkg_list], env=env, text=True, capture_output=True)
        if process.returncode:
            print("Attempt:", i)
            print(process.stdout)
            print(process.stderr, file=sys.stderr)
            process.check_returncode()
        data = json.loads(process.stdout)
        assert data["success"] is True
        for pkg in data["actions"]["LINK"]:
            if pkg["name"] == "bokeh":
                installed_bokeh_versions.append(pkg["version"])
                break
        else:
            raise AssertionError("Didn't find bokeh!")
    assert len(set(installed_bokeh_versions)) == 1


def test_update_from_latest_not_downgrade(
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
) -> None:
    """Based on two issues where an upgrade caused a downgrade in a given package

    Suppose we have two python versions 3.11.2 and 3.11.3. The bug is when:
    $ conda install python | grep python
    python 3.11.3
    $ conda update python | grep python
    python 3.11.2

    Update should not downgrade the package
     - https://github.com/conda/conda-libmamba-solver/issues/71
     - https://github.com/conda/conda-libmamba-solver/issues/156
    """
    with tmp_env(
        "--override-channels",
        "--channel=conda-forge",
        "--solver=rattler",
        "python",
    ) as prefix:
        original_python = PrefixData(prefix).get("python")
        conda_cli(
            "update",
            f"--prefix={prefix}",
            "--solver=rattler",
            "--override-channels",
            "--channel=conda-forge",
            "python",
        )
        update_python = PrefixData(prefix).get("python")
        assert original_python.version == update_python.version


def test_name_only_update_python_honors_named_package_lock(
    tmp_env: TmpEnvFixture,
) -> None:
    args = ("--override-channels", "--channel=defaults", "--solver=rattler")

    def planned_python_version(prefix: Path, command: str, python_spec: str) -> str:
        installed_version = PrefixData(prefix).get("python").version
        process = conda_subprocess(
            command,
            f"--prefix={prefix}",
            *args,
            "--dry-run",
            "--json",
            python_spec,
        )
        for record in json.loads(process.stdout).get("actions", {}).get("LINK", ()):
            if record["name"] == "python":
                return record["version"]
        return installed_version

    with tmp_env("python=3.13", "conda", *args) as prefix:
        installed_minor = PrefixData(prefix).get("python").version.rsplit(".", 1)[0]
        assert planned_python_version(prefix, "update", "python").startswith(f"{installed_minor}.")
        assert planned_python_version(prefix, "install", "python=3.14").startswith("3.14.")

    with tmp_env("python=3.13", *args) as prefix:
        installed_minor = PrefixData(prefix).get("python").version.rsplit(".", 1)[0]
        assert not planned_python_version(prefix, "update", "python").startswith(
            f"{installed_minor}."
        )


_CLASSIC_FLOATS_PYTHON = {
    "classic": "3.14.0",
    "libmamba": "3.13.1",
    "rattler": "3.13.1",
}


def _record(name, version, depends=(), build="0"):
    return {
        "name": name,
        "version": version,
        "build": build,
        "build_number": 0,
        "depends": list(depends),
        "subdir": context.subdir,
        "timestamp": 0,
        "size": 0,
    }


@pytest.mark.parametrize(
    "scenario,command,special,pin,expected_python",
    [
        pytest.param(
            "unrequested-conda",
            ("update", "python"),
            "conda",
            None,
            _CLASSIC_FLOATS_PYTHON,
            id="keep-minor-allow-patch",
        ),
        pytest.param(
            "explicit-python-pin",
            ("update", "python"),
            "conda",
            "python=3.14",
            "3.14.0",
            id="explicit-pin",
        ),
        pytest.param(
            "update-python-and-conda",
            ("update", "python", "conda"),
            "conda",
            None,
            "3.14.0",
            id="update-python-and-conda",
        ),
        pytest.param(
            "unversioned-python-dependency",
            ("update", "python"),
            "console_shortcut",
            None,
            "3.14.0",
            id="unversioned-python-dependency",
        ),
        pytest.param(
            "explicit-python-install",
            ("install", "python=3.14"),
            "conda",
            None,
            "3.14.0",
            id="explicit-python-install",
        ),
        pytest.param(
            "no-special-package",
            ("update", "python"),
            None,
            None,
            "3.14.0",
            id="no-special-package",
        ),
        pytest.param(
            "transitive-python-dependency",
            ("update", "python"),
            "transitive-conda",
            None,
            _CLASSIC_FLOATS_PYTHON,
            id="transitive-python-dependency",
        ),
        pytest.param(
            "update-transitive-conda",
            ("update", "python", "conda"),
            "transitive-conda",
            None,
            "3.14.0",
            id="update-transitive-conda",
        ),
        pytest.param(
            "update-other-python-dependent-package",
            ("update", "python", "python-consumer"),
            "conda",
            None,
            _CLASSIC_FLOATS_PYTHON,
            id="update-other-python-dependent-package",
        ),
        pytest.param(
            "pinned-consumer-releases-conda",
            ("update", "python", "python-consumer"),
            "conda",
            "python-consumer=2.0",
            "3.14.0",
            id="conflicting-request-releases-conda",
        ),
        pytest.param(
            "conda-not-in-history",
            ("update", "python"),
            "conda",
            "python=3.14",
            "3.14.0",
            id="conda-not-in-history",
        ),
        pytest.param(
            "pinned-special-package",
            ("update", "python"),
            "conda",
            "python=3.14\nconda",
            "3.14.0",
            id="pinned-special-package",
        ),
    ],
)
def test_python_updates_match_reference_solvers(
    tmp_path, scenario, command, special, pin, expected_python
):
    channel = tmp_path / "channel"
    prefix = tmp_path / "prefix"
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True)

    available = [
        _record("python", version, build="h_fixture_0_cpython")
        for version in ("3.13.0", "3.13.1", "3.14.0")
    ]
    installed = [available[0]]
    if special == "conda":
        available.extend(
            [
                _record("conda", "1.0", ["python >=3.13,<3.14"], "py313_0"),
                _record("conda", "1.0", ["python >=3.14,<3.15"], "py314_0"),
                _record("conda", "2.0", ["python >=3.14,<3.15"], "py314_0"),
            ]
        )
        installed.append(available[3])
    elif special == "console_shortcut":
        available.append(_record("console_shortcut", "1.0", ["python"]))
        installed.append(available[3])
    elif special == "transitive-conda":
        available.extend(
            [
                _record("conda", "1.0", ["python-helper =1.0"]),
                _record("python-helper", "1.0", ["python >=3.13,<3.14"]),
                _record("conda", "2.0", ["python-helper =2.0"]),
                _record("python-helper", "2.0", ["python >=3.14,<3.15"]),
            ]
        )
        installed.extend(available[3:5])
    if "python-consumer" in command:
        available.extend(
            [
                _record("python-consumer", "1.0", ["python >=3.13"]),
                _record("python-consumer", "2.0", ["python >=3.14"]),
            ]
        )
        installed.append(available[-2])

    def filename(record):
        return f"{record['name']}-{record['version']}-{record['build']}.tar.bz2"

    for subdir in (context.subdir, "noarch"):
        directory = channel / subdir
        directory.mkdir(parents=True)
        packages = {filename(record): record for record in available}
        (directory / "repodata.json").write_text(
            json.dumps(
                {
                    "info": {"subdir": subdir},
                    "packages": packages if subdir == context.subdir else {},
                    "packages.conda": {},
                    "repodata_version": 1,
                }
            )
        )

    for record in installed:
        name = filename(record)
        (metadata / f"{name.removesuffix('.tar.bz2')}.json").write_text(
            json.dumps(
                {
                    **record,
                    "fn": name,
                    "channel": channel.as_uri(),
                    "url": f"{channel.as_uri()}/{context.subdir}/{name}",
                    "files": [],
                }
            )
        )
    specs = [record["name"] for record in installed if record["name"] != "python-helper"]
    specs[0] = "python=3.13"
    if scenario == "conda-not-in-history":
        specs.remove("conda")
    history = ["==> 2026-01-01 00:00:00 <==", "# cmd: conda create", f"# update specs: {specs!r}"]
    history.extend(
        f"+{channel.as_uri()}/{context.subdir}::{filename(record).removesuffix('.tar.bz2')}"
        for record in installed
    )
    (metadata / "history").write_text("\n".join(history) + "\n")
    if pin:
        (metadata / "pinned").write_text(pin + "\n")

    condarc = tmp_path / "condarc"
    condarc.write_text("{}\n")
    env = {
        key: value for key, value in os.environ.items() if not key.startswith(("CONDA_", "MAMBA_"))
    }
    env.update(
        {
            "CONDARC": str(condarc),
            "CONDA_SUBDIR": context.subdir,
            "CONDA_PKGS_DIRS": str(tmp_path / "pkgs"),
            "CONDA_ENVS_PATH": str(tmp_path / "envs"),
            "CONDA_AUTO_UPDATE_CONDA": "false",
            "CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY": "false",
            "CONDA_SAT_SOLVER": "pycosat",
            "CONDA_AGGRESSIVE_UPDATE_PACKAGES": "",
            "CONDA_PINNED_PACKAGES": "",
            "CONDA_REPODATA_USE_ZST": "false",
            "CONDA_REPODATA_USE_SHARDS": "false",
            "CONDA_REPORT_ERRORS": "false",
            "CONDA_NUMBER_CHANNEL_NOTICES": "0",
            "CONDA_ALWAYS_YES": "true",
        }
    )
    original_metadata = {path.name: path.read_bytes() for path in metadata.iterdir()}
    results = {}
    for solver in ("classic", "libmamba", "rattler"):
        process = conda_subprocess(
            command[0],
            "--prefix",
            prefix,
            "--solver",
            solver,
            "--dry-run",
            "--json",
            "--offline",
            "--override-channels",
            "--channel",
            channel.as_uri(),
            "--repodata-fn",
            "repodata.json",
            *command[1:],
            env=env,
            check=False,
        )
        result = json.loads(process.stdout)
        if process.returncode:
            results[solver] = {"error": result.get("exception_name", "UnknownError")}
        else:
            final = {record["name"]: record["version"] for record in installed}
            actions = result.get("actions", {})
            for record in actions.get("UNLINK", []):
                final.pop(record["name"], None)
            final.update({record["name"]: record["version"] for record in actions.get("LINK", [])})
            results[solver] = final
        assert {path.name: path.read_bytes() for path in metadata.iterdir()} == original_metadata

    print(json.dumps({"scenario": scenario, "results": results}, sort_keys=True))
    for solver, result in results.items():
        expected = (
            expected_python[solver] if isinstance(expected_python, dict) else expected_python
        )
        assert result.get("python") == expected, (solver, results)
        assert {record["name"] for record in installed} <= result.keys(), (solver, results)
        if "conda" in command[1:]:
            assert result["conda"] == "2.0", (solver, results)
        if "python-consumer" in command[1:]:
            assert result["python-consumer"] == ("2.0" if expected == "3.14.0" else "1.0"), (
                solver,
                results,
            )


@pytest.mark.skipif(not on_linux, reason="Linux only")
def test_too_aggressive_update_to_conda_forge_packages(tmp_env: TmpEnvFixture) -> None:
    """
    Comes from report in https://github.com/conda/conda-libmamba-solver/issues/240
    We expect a minimum change to the 'base' environment if we only ask for a single package.
    conda classic would just change a few (<5) packages, but libmamba seemed to upgrade
    EVERYTHING it can to conda-forge.

    In July 2024 this test was updated so it updates ca-certificates instead of libzlib to account
    for differences in how conda-forge and defaults package this library.
    """
    with tmp_env("conda", "python", "--override-channels", "--channel=defaults") as prefix:
        cmd = (
            "install",
            "-p",
            prefix,
            "-c",
            "conda-forge",
            "ca-certificates",
            "--json",
            "--dry-run",
            "-y",
            "-vvv",
        )
        env = os.environ.copy()
        env.pop("CONDA_SOLVER", None)
        # libmamba seems to take these more seriously than conda... by default the aggressive
        # update list is ca-certificates, openssl and certifi. We clear it in this test so we
        # can only test the CLI specs _we_ pass.
        env["CONDA_AGGRESSIVE_UPDATE_PACKAGES"] = ""
        p_classic = conda_subprocess(*cmd, "--solver=classic", explain=True, env=env)
        p_rattler = conda_subprocess(*cmd, "--solver=rattler", explain=True, env=env)
        data_classic = json.loads(p_classic.stdout)
        data_rattler = json.loads(p_rattler.stdout)
        assert (
            len(data_rattler.get("actions", {}).get("LINK", ()))
            <= len(data_classic.get("actions", {}).get("LINK", ()))
            <= 1
        )


@pytest.mark.skipif(context.subdir != "linux-64", reason="Linux-64 only")
def test_pinned_with_cli_build_string(tmp_env: TmpEnvFixture) -> None:
    specs = (
        "scipy=1.7.3=py37hf2a6cf1_0",
        "python=3.7.3",
        "pandas=1.2.5=py37h295c915_0",
    )
    channels = (
        "--override-channels",
        "--channel=conda-forge",
        "--channel=defaults",
    )
    with tmp_env(*specs, *channels) as prefix:
        Path(prefix, "conda-meta").mkdir(exist_ok=True)
        Path(prefix, "conda-meta", "pinned").write_text(
            dedent(
                """
                python ==3.7.3
                pandas ==1.2.5 py37h295c915_0
                scipy ==1.7.3 py37hf2a6cf1_0
                """
            ).lstrip()
        )
        # We ask for the same packages or name-only, it should be compatible
        for valid_specs in (specs, ("python", "pandas", "scipy")):
            p = conda_subprocess(
                "install",
                "-p",
                prefix,
                *valid_specs,
                *channels,
                "--dry-run",
                "--json",
                explain=True,
                check=False,
            )
            data = json.loads(p.stdout)
            assert data.get("success")
            assert data["message"] == "All requested packages already installed."

        # However if we ask for a different version, it should fail
        invalid_specs = ("python=3.8", "pandas=1.2.4", "scipy=1.7.2")
        p = conda_subprocess(
            "install",
            "-p",
            prefix,
            *invalid_specs,
            *channels,
            "--dry-run",
            "--json",
            explain=True,
            check=False,
        )
        data = json.loads(p.stdout)
        assert not data.get("success")
        assert data["exception_name"] == "SpecsConfigurationConflictError"

        non_existing_specs = ("python=0", "pandas=1000", "scipy=24")
        p = conda_subprocess(
            "install",
            "-p",
            prefix,
            *non_existing_specs,
            *channels,
            "--dry-run",
            "--json",
            explain=True,
            check=False,
        )
        data = json.loads(p.stdout)
        assert not data.get("success")
        assert data["exception_name"] in (
            "PackagesNotFoundError",
            "PackagesNotFoundInChannelsError",
        )


def test_constraining_pin_and_requested():
    env = os.environ.copy()
    env["CONDA_PINNED_PACKAGES"] = "python=3.9"

    # This should fail because it contradicts the pinned packages
    p = conda_subprocess(
        "create",
        "-n",
        "unused",
        "--dry-run",
        "--json",
        "python=3.10",
        "--override-channels",
        "-c",
        "conda-forge",
        env=env,
        explain=True,
        check=False,
    )
    data = json.loads(p.stdout)
    assert not data.get("success")
    assert data["exception_name"] == "SpecsConfigurationConflictError"

    # This is ok because it's a no-op
    p = conda_subprocess(
        "create",
        "-n",
        "unused",
        "--dry-run",
        "--json",
        "python",
        env=env,
        explain=True,
        check=False,
    )
    data = json.loads(p.stdout)
    assert data.get("success")
    assert data.get("dry_run")


def test_locking_pins(
    monkeypatch: MonkeyPatch,
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
) -> None:
    monkeypatch.setenv("CONDA_PINNED_PACKAGES", "zlib")
    with tmp_env("zlib") as prefix:
        # Should install just fine
        zlib = PrefixData(prefix).get("zlib")
        assert zlib

        # This should fail because it contradicts the lock packages
        out, err, retcode = conda_cli(
            "install",
            f"--prefix={prefix}",
            "--dry-run",
            "zlib=1.2.11",
            "--json",
            raises=SpecsConfigurationConflictError,
        )
        assert str(zlib) in retcode.value.dump_map()["error"]

        # This is a no-op and ok. It won't involve changes.
        try:
            out, err, retcode = conda_cli(
                "install",
                f"--prefix={prefix}",
                "zlib",
                "--dry-run",
                "--json",
            )
        except DryRunExit:
            assert True
        else:
            data = json.loads(out)
            assert data.get("success")
            assert data["message"] == "All requested packages already installed."


def test_ca_certificates_pins(tmp_env: TmpEnvFixture, conda_cli: CondaCLIFixture) -> None:
    ca_certificates_pin = "ca-certificates=2023"
    with tmp_env() as prefix:
        Path(prefix, "conda-meta").mkdir(exist_ok=True)
        Path(prefix, "conda-meta", "pinned").write_text(f"{ca_certificates_pin}\n")

        for cli_spec in (
            "ca-certificates",
            "ca-certificates=2023",
            "ca-certificates>0",
            "ca-certificates<2024",
            "ca-certificates!=2022",
        ):
            out, err, retcode = conda_cli(
                "install",
                f"--prefix={prefix}",
                cli_spec,
                "--dry-run",
                "--json",
                "--override-channels",
                "--channel=conda-forge",
                raises=DryRunExit,
            )
            data = json.loads(out)
            assert data.get("success")
            assert data.get("dry_run")

            for pkg in data["actions"]["LINK"]:
                if pkg["name"] == "ca-certificates":
                    assert pkg["version"].startswith("2023."), cli_spec
                    break
            else:
                raise AssertionError("ca-certificates not found in LINK actions")


def test_python_update_should_not_uninstall_history(
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
) -> None:
    """
    https://github.com/conda/conda-libmamba-solver/issues/341

    Original report complained about an upgrade to Python 3.12 removing numpy from the
    (originally) py311 environment because at that point in time numpy for py312 was not yet
    available in defaults. Since at some point it will be, we will test for similar behavior
    here, but in a way that we know will never be reverted: typing_extensions being available for
    Python 2.7.

    Given a Python 3.8 + typing-extensions environment, the solver should not allow us to
    change to Python 2.7 because typing-extensions is in history, and the only solution to get
    Python 2.7 is to remove it. Hence, we expect a conflict that mentions both.
    """
    channels = "--override-channels", "-c", "conda-forge"
    solver = "--solver", "rattler"
    # Py27 not available in osx-arm64
    platform = ("--platform", "osx-64") if context.subdir == "osx-arm64" else ()
    with tmp_env("python=3.8", "typing_extensions>=4.8", *channels, *solver, *platform) as prefix:
        assert package_is_installed(prefix, "python=3.8")
        assert package_is_installed(prefix, "typing_extensions>=4.8")
        with pytest.raises(
            RattlerUnsatisfiableError,
            match=r"python 2\.7.|\n*typing_extensions",
        ):
            conda_cli(
                "install",
                f"--prefix={prefix}",
                "python=2.7",
                *channels,
                *solver,
                "--dry-run",
            )


def test_python_downgrade_with_pins_removes_truststore(tmp_env: TmpEnvFixture) -> None:
    """
    https://github.com/conda/conda-libmamba-solver/issues/354
    """
    channels = "--override-channels", "-c", "conda-forge"
    solver = "--solver", "rattler"
    with tmp_env("python=3.10", "conda=23.9", *channels, *solver) as prefix:
        zstd_version = PrefixData(prefix).get("zstd").version
        for pin in (None, "zstd", f"zstd={zstd_version}"):
            env = os.environ.copy()
            if pin:
                env["CONDA_PINNED_PACKAGES"] = pin
            p = conda_subprocess(
                "install",
                f"--prefix={prefix}",
                *channels,
                *solver,
                "--dry-run",
                "--json",
                "python=3.9",
                env=env,
                check=False,
            )
            data = json.loads(p.stdout)
            assert p.returncode == 0
            assert data.get("success")
            assert data.get("dry_run")
            link_dict = {pkg["name"]: pkg for pkg in data["actions"]["LINK"]}
            unlink_dict = {pkg["name"]: pkg for pkg in data["actions"]["UNLINK"]}
            assert link_dict["python"]["version"].startswith("3.9.")
            assert "truststore" in unlink_dict
            if pin:
                # shouldn't have changed!
                assert unlink_dict.get("zstd") == link_dict.get("zstd")


@pytest.mark.parametrize("spec", ("__glibc", "__unix", "__linux", "__osx", "__win"))
def test_install_virtual_packages(conda_cli: CondaCLIFixture, spec: str) -> None:
    """
    Ensures a solver knows how to deal with virtual specs in the CLI.
    This mean succeeding only if the virtual package is available.
    https://github.com/conda/conda-libmamba-solver/issues/480

    TODO: Remove once https://github.com/conda/conda/pull/13784 is merged
    """
    if any(
        [
            on_linux and spec in ("__glibc", "__unix", "__linux"),
            on_mac and spec in ("__unix", "__osx"),
            on_win and spec == "__win",
        ]
    ):
        raises = DryRunExit  # success
    else:
        raises = (UnsatisfiableError, PackagesNotFoundError)
    conda_cli("create", "--dry-run", "--offline", spec, raises=raises)


def test_urls_are_percent_decoded(tmp_path: Path) -> None:
    solver = Solver(
        prefix=tmp_path, channels=["conda-forge"], specs_to_add=["x264"], command="create"
    )
    records = solver.solve_final_state()
    for record in records:
        if record.name == "x264":
            print(record.url)
            assert "!" in record.url
            assert "%" not in record.url
            break
    else:
        pytest.fail("Solution didn't include x264")


def test_prune_existing_env(
    conda_cli: CondaCLIFixture,
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
) -> None:
    """
    https://github.com/conda/conda-libmamba-solver/issues/595
    """
    (tmp_path / "env.yml").write_text(
        dedent(
            """
        channels:
        - defaults
        dependencies:
        - ca-certificates
        """
        )
    )
    with tmp_env("zstd") as prefix:
        out, err, rc = conda_cli(
            "env",
            "update",
            f"--prefix={prefix}",
            f"--file={tmp_path / 'env.yml'}",
            "--prune",
        )
        assert rc == 0
        PrefixData._cache_.clear()
        assert not PrefixData(prefix).get("zstd", None)
        assert PrefixData(prefix).get("ca-certificates")


def test_prune_existing_env_dependencies_are_solved(
    conda_cli: CondaCLIFixture,
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
) -> None:
    """
    https://github.com/conda/conda-libmamba-solver/issues/595
    """
    (tmp_path / "env.yml").write_text(
        dedent(
            """
            channels:
            - conda-forge
            dependencies:
            - python=3.12
            - numpy=2.1.2
            """
        )
    )
    with tmp_env("python=3.12") as prefix:
        out, err, rc = conda_cli(
            "env",
            "update",
            f"--prefix={prefix}",
            f"--file={tmp_path / 'env.yml'}",
            "--prune",
            "-vv",
        )
        print(out)
        print(err, file=sys.stderr)
        assert rc == 0
        PrefixData._cache_.clear()
        assert PrefixData(prefix).get("python").version.startswith("3.12")
        assert PrefixData(prefix).get("numpy")
        out, err, rc = conda_cli("run", f"--prefix={prefix}", "python", "-c", "import numpy")
        print(out)
        print(err, file=sys.stderr)
        assert rc == 0


def test_satisfied_skip_solve_matchspec(
    conda_cli: CondaCLIFixture, tmp_env: TmpEnvFixture
) -> None:
    with tmp_env("ca-certificates") as prefix:
        conda_cli(
            "install",
            f"--prefix={prefix}",
            "--satisfied-skip-solve",
            "ca-certificates>10000",
            raises=PackagesNotFoundError,
        )


# @pytest.mark.skipif(context.subdir != "linux-64", reason="Linux x64 only")
@pytest.mark.parametrize(
    "specs",
    (
        pytest.param(("pytorch", "torchvision"), id="pytorch"),
        pytest.param(("pytorch>0", "torchvision"), id="pytorch>0"),
        pytest.param(("pytorch=2", "torchvision"), id="pytorch=2"),
    ),
)
def test_pytorch_gpu(specs, tmp_path):
    """
    https://github.com/conda/conda-libmamba-solver/issues/646

    This test must run in a subprocess because it's sensitive to side effects
    from other tests. There must be some global state in the libmamba Database / Pool
    objects. When run in isolation, it always passed.
    """
    env = os.environ.copy()
    env["CONDA_OVERRIDE_CUDA"] = "12.6"
    env["CONDA_OVERRIDE_GLIBC"] = "2.30"
    env["CONDA_OVERRIDE_LINUX"] = "5.15.167.4"
    env["CONDA_OVERRIDE_ARCHSPEC"] = "skylake"
    env["CONDA_OVERRIDE_OSX"] = ""

    p = conda_subprocess(
        "create",
        "--dry-run",
        "--override-channels",
        "--channel=conda-forge",
        "--platform=linux-64",
        "--json",
        *specs,
        env=env,
    )
    result = json.loads(p.stdout)
    assert result["success"]
    for record in result["actions"]["LINK"]:
        if record["name"] == "pytorch":
            print(record)
            assert "cuda" in record["build_string"]
            break
    else:
        raise AssertionError("No pytorch found")


def test_channel_subdir_set_correctly(tmp_env: TmpEnvFixture) -> None:
    """
    https://github.com/conda/conda-libmamba-solver/issues/662
    """
    with tmp_env(
        "--override-channels",
        "--channel=conda-forge",
        "--solver=rattler",
        "tzdata",
        "bzip2",
    ) as prefix:
        cm_path: Path = prefix / "conda-meta"
        for prec_path in cm_path.glob("*.json"):
            if prec_path.name.startswith("bzip2-"):
                payload = json.loads(prec_path.read_text())
                assert not payload["channel"].endswith("noarch")
            if prec_path.name.startswith("tzdata-"):
                payload = json.loads(prec_path.read_text())
                assert payload["channel"].endswith("noarch")


def test_conditional_specs_in_cli(conda_cli):
    out, err, exc = conda_cli(
        "create",
        "--dry-run",
        "--json",
        "--solver=rattler",
        "--channel=conda-forge",
        "--override-channels",
        "libzlib=1.3",
        "ca-certificates[when='libzlib=1.2']",
        raises=DryRunExit,
    )
    data = json.loads(out)
    has_zlib = False
    for entry in data["actions"]["LINK"]:
        if entry["name"] == "libzlib":
            has_zlib = True
        elif entry["name"] == "ca-certificates":
            raise AssertionError(
                f"ca-certificates should not be installed; got {data['actions']['LINK']}"
            )
    assert has_zlib


def _add_pip_repodata(include_pip: bool = True) -> dict:
    def record(name: str, version: str, *depends: str) -> dict:
        return {
            "name": name,
            "version": version,
            "build": "0",
            "build_number": 0,
            "depends": list(depends),
        }

    packages = {
        "application-2-1.0-0.tar.bz2": record("application-2", "1.0", "python 2.*"),
        "application-3-1.0-0.tar.bz2": record("application-3", "1.0", "python 3.*"),
        "application-4-1.0-0.tar.bz2": record("application-4", "1.0", "python 4.*"),
        "python-2.7.18-0.tar.bz2": record("python", "2.7.18"),
        "python-3.13.0-0.tar.bz2": record("python", "3.13.0"),
        "python-4.0.0-0.tar.bz2": record("python", "4.0.0"),
        "standalone-1.0-0.tar.bz2": record("standalone", "1.0"),
    }
    if include_pip:
        packages["pip-25.0-0.tar.bz2"] = record("pip", "25.0")
    return {
        "info": {"subdir": "noarch"},
        "packages": packages,
        "packages.conda": {},
        "repodata_version": 1,
    }


def _add_pip_index(
    tmp_path: Path,
    in_state: SolverInputState,
    repodata: dict,
    repodata_use_shards: bool,
) -> RattlerIndexHelper:
    if repodata_use_shards:
        url = "https://example.invalid/noarch"
        shardlike = ShardLike(repodata, url)
        for record in repodata["packages"].values():
            shardlike.visit_package(record["name"])
        return RattlerIndexHelper(
            channels=[Channel(url)],
            subdirs=("noarch",),
            in_state=in_state,
            build_repodata_subset=lambda *_args, **_kwargs: {url: shardlike},
        )

    channel = tmp_path / "channel" / "noarch"
    channel.mkdir(parents=True)
    (channel / "repodata.json").write_text(json.dumps(repodata))
    return RattlerIndexHelper(
        channels=[Channel(str(channel.parent))],
        subdirs=("noarch",),
    )


@pytest.mark.parametrize("repodata_use_shards", (False, True), ids=("repodata", "shards"))
def test_add_pip_as_python_dependency(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    repodata_use_shards: bool,
) -> None:
    monkeypatch.setattr(context, "repodata_use_shards", repodata_use_shards)
    prefix = tmp_path / "env"
    requested = ("application-3",)
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_add=requested,
    )
    in_state = SolverInputState(prefix, requested=requested)
    index = _add_pip_index(
        tmp_path,
        in_state,
        _add_pip_repodata(),
        repodata_use_shards,
    )

    # Check that enabling pip does not affect later solves using the same index.
    for add_pip in (False, True, False):
        monkeypatch.setattr(context, "add_pip_as_python_dependency", add_pip)
        out_state = SolverOutputState(solver_input_state=in_state)
        solution = solver._solve_attempt(in_state, out_state, index)

        assert isinstance(solution, list)
        assert ("pip" in {record.name.source for record in solution}) is add_pip
        solver._export_solved_records(solution, out_state)
        assert ("pip" in out_state.records["python"].depends) is add_pip


def test_add_pip_in_index_search(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    prefix = tmp_path / "env"
    in_state = SolverInputState(prefix, requested=("python",))
    index = _add_pip_index(
        tmp_path,
        in_state,
        _add_pip_repodata(),
        repodata_use_shards=False,
    )

    # Check that enabling pip does not affect later searches using the same index.
    for add_pip in (False, True, False):
        monkeypatch.setattr(context, "add_pip_as_python_dependency", add_pip)
        dependencies = {
            record.version: "pip" in record.depends for record in index.search("python")
        }

        assert dependencies == {
            "2.7.18": add_pip,
            "3.13.0": add_pip,
            "4.0.0": False,
        }


def test_add_pip_does_not_patch_locked_python(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(context, "add_pip_as_python_dependency", True)

    prefix = tmp_path / "env"
    in_state = SolverInputState(prefix, requested=("standalone",))
    in_state.prefix_data._prefix_records["python"] = PrefixRecord(
        name="python",
        version="3.13.0",
        build="0",
        build_number=0,
        channel="https://example.invalid/noarch",
        subdir="noarch",
        fn="python-3.13.0-0.tar.bz2",
        url="https://example.invalid/noarch/python-3.13.0-0.tar.bz2",
        depends=(),
    )
    in_state._history["python"] = MatchSpec("python")
    out_state = SolverOutputState(solver_input_state=in_state)
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_add=("standalone",),
    )
    index = _add_pip_index(
        tmp_path,
        in_state,
        _add_pip_repodata(),
        repodata_use_shards=False,
    )

    out_state = solver._solving_loop(in_state, out_state, index)

    assert set(out_state.records) == {"python", "standalone"}
    assert "pip" not in out_state.records["python"].depends


def test_add_pip_requires_a_pip_candidate(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(context, "add_pip_as_python_dependency", True)

    prefix = tmp_path / "env"
    requested = ("application-3",)
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_add=requested,
    )
    in_state = SolverInputState(prefix, requested=requested)
    out_state = SolverOutputState(solver_input_state=in_state)
    index = _add_pip_index(
        tmp_path,
        in_state,
        _add_pip_repodata(include_pip=False),
        repodata_use_shards=False,
    )

    result = solver._solve_attempt(in_state, out_state, index)

    assert isinstance(result, RattlerSolverError)
    assert "pip *, for which no candidates were found" in str(result)


@pytest.mark.usefixtures("solver_rattler")
def test_maybe_raise_for_problems_survives_bare_extras_brackets(
    tmp_path: Path,
) -> None:
    """
    Regression test: rattler's solver renders a requested "extra" as a bare
    bracket synthetic name (`httpx[cli]`, no `extras=` key) in its
    human-readable diagnostic text. Re-parsing that text as a conda
    MatchSpec must not crash with InvalidMatchSpec; it should degrade to a
    name(+version) MatchSpec so the real "no candidates"/"unsatisfiable"
    problem can still be reported.
    """
    prefix = tmp_path / "env"
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_add=("httpx[extras=cli]",),
    )
    in_state = SolverInputState(prefix, requested=("httpx[extras=cli]",))
    out_state = SolverOutputState(solver_input_state=in_state)
    problems = (
        "Cannot solve the request because of:\n"
        "  ├─ No candidates were found for httpx[cli] ==0.28.0.\n"
    )

    with pytest.raises(PackagesNotFoundError) as exc_info:
        solver._maybe_raise_for_problems(problems, in_state, out_state)

    assert "httpx==0.28.0" in str(exc_info.value)


@pytest.mark.usefixtures("solver_rattler")
@pytest.mark.parametrize(
    "diagnostic_spec",
    (
        pytest.param("httpx [extras=[cli]]", id="bare-extras-conflict"),
        pytest.param(
            'httpx [extras=[cli], md5="7cb326b464b75a04aa57954631097aa4"]',
            id="truncated-extras-and-md5",
        ),
    ),
)
def test_maybe_raise_for_problems_preserves_extras_conflict(
    tmp_path: Path, diagnostic_spec: str
) -> None:
    """Preserve the solver diagnostic reported in conda/conda#16724 after a retry."""
    prefix = tmp_path / "env"
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_add=(diagnostic_spec,),
    )
    in_state = SolverInputState(prefix, requested=(diagnostic_spec,))
    out_state = SolverOutputState(solver_input_state=in_state)
    problems = (
        f"Cannot solve the request because of: {diagnostic_spec} "
        "cannot be installed because there are no viable options:\n"
        "└─ httpx 0.28.0 would require\n"
        "   └─ rich <14,>=10, for which no candidates were found.\n"
        "The following packages are incompatible\n"
        "└─ httpx[cli] can be installed with any of the following options:\n"
        "   └─ httpx[cli]\n"
    )

    solver._maybe_raise_for_problems(problems, in_state, out_state)

    with pytest.raises(RattlerUnsatisfiableError) as exc_info:
        solver._maybe_raise_for_problems(problems, in_state, out_state)

    assert str(exc_info.value) == problems
    assert exc_info.value.allow_retry is False


@pytest.mark.parametrize(
    "python_depends,expected_names",
    (
        pytest.param(("pip",), set(), id="python-depends-on-pip"),
        pytest.param((), {"python"}, id="legacy-python-without-pip-dependency"),
    ),
)
def test_removing_pip_respects_installed_python_metadata(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    python_depends: tuple[str, ...],
    expected_names: set[str],
) -> None:
    monkeypatch.setattr(context, "add_pip_as_python_dependency", True)

    prefix = tmp_path / "env"
    requested = ("pip",)
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=("noarch",),
        specs_to_remove=requested,
        command="remove",
    )
    in_state = SolverInputState(prefix, requested=requested, command="remove")
    for name, version, depends in (
        ("python", "3.13.0", python_depends),
        ("pip", "25.0", ()),
    ):
        filename = f"{name}-{version}-0.tar.bz2"
        in_state.prefix_data._prefix_records[name] = PrefixRecord(
            name=name,
            version=version,
            build="0",
            build_number=0,
            channel="https://example.invalid/noarch",
            subdir="noarch",
            fn=filename,
            url=f"https://example.invalid/noarch/{filename}",
            depends=depends,
        )
    in_state._history["python"] = MatchSpec("python")
    out_state = SolverOutputState(solver_input_state=in_state)
    repodata = _add_pip_repodata()
    for filename in tuple(repodata["packages"]):
        if filename.startswith(("python-2.", "python-4.")):
            repodata["packages"].pop(filename)
    index = _add_pip_index(
        tmp_path,
        in_state,
        repodata,
        repodata_use_shards=False,
    )

    out_state = solver._solving_loop(in_state, out_state, index)

    assert set(out_state.records) == expected_names
    if "python" in expected_names:
        assert out_state.records["python"].depends == python_depends


def test_add_pip_from_offline_package_cache(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(context, "add_pip_as_python_dependency", True)
    packages_dir = tmp_path / "pkgs"
    packages_dir.mkdir()
    for name, version in (("python", "3.13.0"), ("pip", "25.0")):
        filename = f"{name}-{version}-0.conda"
        info_dir = packages_dir / f"{name}-{version}-0" / "info"
        info_dir.mkdir(parents=True)
        record = {
            "name": name,
            "version": version,
            "build": "0",
            "build_number": 0,
            "depends": [],
            "subdir": context.subdir,
            "fn": filename,
            "channel": f"https://example.invalid/{context.subdir}",
            "url": f"https://example.invalid/{context.subdir}/{filename}",
        }
        (info_dir / "index.json").write_text(json.dumps(record))
        (info_dir / "repodata_record.json").write_text(json.dumps(record))

    prefix = tmp_path / "env"
    requested = ("python",)
    solver = Solver(
        prefix=prefix,
        channels=(),
        subdirs=(context.subdir, "noarch"),
        specs_to_add=requested,
    )
    in_state = SolverInputState(prefix, requested=requested)
    out_state = SolverOutputState(solver_input_state=in_state)
    index = RattlerIndexHelper(
        channels=(),
        subdirs=(context.subdir, "noarch"),
        pkgs_dirs=(str(packages_dir),),
        in_state=in_state,
    )

    solution = solver._solve_attempt(in_state, out_state, index)

    assert isinstance(solution, list)
    assert {record.name.source for record in solution} == {"python", "pip"}


def test_conditional_specs_in_repodata_virtual(conda_cli):
    out, err, exc = conda_cli(
        "create",
        "--dry-run",
        "--json",
        "--solver=rattler",
        f"--channel={DATA / 'conditional-repodata'}",
        "--override-channels",
        "package",
        raises=DryRunExit,
    )
    data = json.loads(out)
    expected_dependency = f"{context.subdir.split('-')[0]}-dependency"
    to_install = {entry["name"] for entry in data["actions"]["LINK"]}
    assert "package" in to_install
    assert expected_dependency in to_install


def test_conditional_specs_in_repodata_side1(conda_cli):
    out, err, exc = conda_cli(
        "create",
        "--dry-run",
        "--json",
        "--solver=rattler",
        f"--channel={DATA / 'conditional-repodata'}",
        "--override-channels",
        "conditional-dependency",
        "side-dependency=0.1",
        raises=DryRunExit,
    )
    data = json.loads(out)
    to_install = {entry["name"] for entry in data["actions"]["LINK"]}
    assert "conditional-dependency" in to_install
    assert "side-dependency" in to_install
    # We do NOT want 'package' here. It should only show up when side-dependency=0.2 is requested.
    assert "package" not in to_install


def test_conditional_specs_in_repodata_side2(conda_cli):
    out, err, exc = conda_cli(
        "create",
        "--dry-run",
        "--json",
        "--solver=rattler",
        f"--channel={DATA / 'conditional-repodata'}",
        "--override-channels",
        "conditional-dependency",
        "side-dependency=0.2",
        raises=DryRunExit,
    )
    data = json.loads(out)
    to_install = {entry["name"] for entry in data["actions"]["LINK"]}
    assert "conditional-dependency" in to_install
    assert "side-dependency" in to_install
    # We DO want 'package' here. It should only show up when side-dependency=0.2 is requested.
    assert "package" in to_install


def test_python_does_not_change_unless_wanted(
    tmp_env: TmpEnvFixture, conda_cli: CondaCLIFixture
) -> None:
    """
    Ensure that the solver does not do extra work when trying to install something already there.
    If we install a slightly older python (3.11.10, but 3.11.14 is available at the time of
    writing) along with colorama, a 2nd colorama installation should NOT cause a python update
    unless the user opts out the freezing strategy (default): --update-deps, requesting python;
    both work.
    """
    args = "--override-channels", "--channel=conda-forge", "--solver=rattler"
    with tmp_env(
        *args,
        "python=3.11.10",
        "colorama",
    ) as prefix:
        out, err, rc = conda_cli(
            "install",
            *args,
            f"--prefix={prefix}",
            "--json",
            "--dry-run",
            "--freeze-installed",  # this is the default
            "colorama",
        )
        assert rc == 0
        assert json.loads(out)["message"] == "All requested packages already installed."

        out, err, rc = conda_cli(
            "install",
            *args,
            f"--prefix={prefix}",
            "--json",
            "--dry-run",
            "--update-specs",  # we don't freeze, but history still pins python so nothing changes
            "colorama",
        )
        assert rc == 0
        assert json.loads(out)["message"] == "All requested packages already installed."

        out, err, rc = conda_cli(
            "install",
            *args,
            f"--prefix={prefix}",
            "--json",
            "--dry-run",
            "--update-deps",  # now we do force a python update
            "colorama",
            raises=DryRunExit,
        )
        data = json.loads(out)
        link_names = {pkg["name"] for pkg in data["actions"]["LINK"]}
        unlink_names = {pkg["name"] for pkg in data["actions"]["UNLINK"]}
        assert "python" in unlink_names.intersection(link_names)

        out, err, rc = conda_cli(
            "install",
            *args,
            f"--prefix={prefix}",
            "--json",
            "--dry-run",
            "python",  # adding a bare python here also causes the update
            "colorama",
            raises=DryRunExit,
        )
        data = json.loads(out)
        link_names = {pkg["name"] for pkg in data["actions"]["LINK"]}
        unlink_names = {pkg["name"] for pkg in data["actions"]["UNLINK"]}
        assert "python" in unlink_names.intersection(link_names)


@pytest.mark.usefixtures("solver_rattler")
def test_installed_packages_included_in_solver(
    tmp_env: TmpEnvFixture, conda_cli: CondaCLIFixture, tmp_path: PathLike
) -> None:
    """
    Test that installed packages are included in the solver's consideration when
    updating all packages.

    ref: https://github.com/conda/conda-rattler-solver/issues/88
    """
    tmp_channel = tmp_path / "channel"
    repo = Path(__file__).parent / "data/mamba_repo"
    shutil.copytree(repo, tmp_channel)
    with tmp_env("test-package", "--channel", tmp_channel) as prefix:
        _, err, rc = conda_cli(
            "update",
            "--all",
            f"--prefix={prefix}",
        )
        assert rc == 0, err


@pytest.mark.benchmark
@pytest.mark.parametrize(
    "channel_still_present", [True, False], ids=["channel-present", "channel-missing"]
)
def test_installed_packages_included_in_solver_benchmark(
    benchmark: BenchmarkFixture,
    tmp_env: TmpEnvFixture,
    tmp_path: Path,
    channel_still_present: bool,
) -> None:
    """
    Benchmark of the same scenario covered by ``test_installed_packages_included_in_solver``,
    but calling ``RattlerSolver.solve_final_state()`` directly (instead of going through
    ``conda_cli``) so we can measure the solver's own performance.

    The ``channel-missing`` case reproduces the original bug report: the channel an installed
    package came from is no longer part of the configured channels, so the solver has to fall
    back to its "missing installed" handling to avoid dropping the package. The
    ``channel-present`` case is the same setup without that fallback, to compare its overhead.

    ref: https://github.com/conda/conda-rattler-solver/issues/88
    """
    tmp_channel = tmp_path / "channel"
    repo = Path(__file__).parent / "data/mamba_repo"
    shutil.copytree(repo, tmp_channel)

    empty_channel = tmp_path / "empty_channel"
    (empty_channel / "noarch").mkdir(parents=True)
    (empty_channel / "noarch" / "repodata.json").write_text(
        json.dumps({"info": {"subdir": "noarch"}, "packages": {}, "packages.conda": {}})
    )

    with tmp_env("test-package", "--channel", tmp_channel) as prefix:
        solver = Solver(
            prefix=prefix,
            channels=[str(tmp_channel if channel_still_present else empty_channel)],
            command="update",
        )

        def run():
            return solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)

        solution = benchmark(run)
        assert "test-package" in {record.name for record in solution}


@pytest.mark.parametrize(
    "channel_priority,expected_foo",
    [
        ("strict", "1.0"),
        ("flexible", "1.0"),
        ("disabled", "2.0"),
    ],
)
def test_channel_priority_version_against_channel_order(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    channel_priority: str,
    expected_foo: str,
) -> None:
    """
    The higher-priority channel carries only ``foo 1.0``, while the
    lower-priority channel carries ``foo 2.0``. Strict and flexible priority
    should resolve ``foo`` from the higher-priority channel. However, only
    disabled priority should trade the channel order for the newer version.
    """
    monkeypatch.setenv("CONDA_CHANNEL_PRIORITY", channel_priority)
    reset_context()

    channel_a = tmp_path / "channel-a"
    _make_noarch_package(channel_a, "foo", "1.0")
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "foo", "2.0")

    solver = Solver(
        prefix=str(tmp_path / "prefix"),
        channels=[Channel(str(channel_a)), Channel(str(channel_b))],
        subdirs=("noarch",),
        specs_to_add=("foo",),
    )
    solution = solver.solve_final_state()
    packages = {record.name: record.version for record in solution}
    assert packages == {"foo": expected_foo}


@pytest.mark.parametrize(
    "channel_priority",
    ["strict", "flexible", "disabled"],
)
@pytest.mark.usefixtures("solver_rattler")
def test_explicit_update_keeps_installed_package_whose_channel_is_gone(
    tmp_path: Path,
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
    monkeypatch: MonkeyPatch,
    channel_priority: str,
) -> None:
    """
    ``bar`` (installed) depends on ``foo>=2``. ``foo`` was installed at 2.0 from a channel that
    is no longer configured; the only active channel now offers ``foo`` at 1.0. Explicitly
    requesting an update of ``foo`` should keep the installed 2.0 (the only version that keeps
    ``bar`` satisfiable) instead of failing outright.

    Test that ``conda update`` will not change the installed packages, and that ``conda install``
    will raise ``RattlerUnsatisfiableError``.
    """
    monkeypatch.setenv("CONDA_CHANNEL_PRIORITY", channel_priority)
    reset_context()

    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "foo", "2.0")
    _make_noarch_package(channel_b, "bar", "1.0", depends=("foo>=2",))

    channel_a = tmp_path / "channel-a"
    _make_noarch_package(channel_a, "foo", "1.0")

    with tmp_env("--override-channels", f"--channel={channel_b}", "foo", "bar") as prefix:
        out, err, rc = conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            f"--channel={channel_a}",
            "--dry-run",
            "--json",
            "foo",
        )
        assert rc == 0, err
        assert json.loads(out).get("message") == "All requested packages already installed."

        with pytest.raises(RattlerUnsatisfiableError):
            conda_cli(
                "install",
                f"--prefix={prefix}",
                "--override-channels",
                f"--channel={channel_a}",
                "--dry-run",
                "--json",
                "foo==1",
            )


@pytest.mark.parametrize(
    "channel_priority",
    ["strict", "flexible", "disabled"],
)
def test_channel_priority_keeps_installed_dependency_from_removed_channel(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    channel_priority: str,
    tmp_env: TmpEnvFixture,
) -> None:
    """
    An active channel that happens to also publish an older `foo` must not
    take precedence over the already-installed, newer `foo` if it is a
    dependency of another package (bar).
    """
    monkeypatch.setenv("CONDA_CHANNEL_PRIORITY", channel_priority)
    reset_context()

    # "bar" and its dependency "foo=2.0" were originally installed from "chan-b",
    # which is no longer part of the active channel list below.
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "foo", "2.0")
    _make_noarch_package(channel_b, "bar", "1.0", depends=("foo>=2",))

    # The only active channel, "chan-a", happens to also publish "foo", but only 1.0.
    chan_a = tmp_path / "chan-a"
    (chan_a / "noarch").mkdir(parents=True)
    (chan_a / "noarch" / "repodata.json").write_text(
        json.dumps(
            {
                "info": {"subdir": "noarch"},
                "packages": {
                    "foo-1.0-0.tar.bz2": {
                        "build": "0",
                        "build_number": 0,
                        "depends": [],
                        "constrains": [],
                        "md5": "0" * 32,
                        "name": "foo",
                        "noarch": "generic",
                        "sha256": "0" * 64,
                        "size": 1,
                        "subdir": "noarch",
                        "timestamp": 0,
                        "version": "1.0",
                    },
                },
                "packages.conda": {},
                "removed": [],
                "repodata_version": 1,
            }
        )
    )

    with tmp_env("--override-channels", f"--channel={channel_b}", "foo", "bar") as prefix:
        solver = Solver(
            prefix=prefix,
            channels=[Channel(str(chan_a))],
            subdirs=("noarch",),
        )
        solution = solver.solve_final_state(
            update_modifier=UpdateModifier.UPDATE_ALL, should_retry_solve=True
        )
        packages = {pkg.name: pkg.version for pkg in solution}
        assert "foo" in packages
        assert packages["foo"] == "2.0"
        assert "bar" in packages
        assert packages["bar"] == "1.0"


@pytest.mark.parametrize(
    "channel_priority",
    ["strict", "flexible", "disabled"],
)
def test_channel_priority_updates_installed_dependency(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    channel_priority: str,
    tmp_env: TmpEnvFixture,
) -> None:
    """
    An active channel publishes a newer `foo` must take precedence
    over the already-installed, `foo`.
    """
    monkeypatch.setenv("CONDA_CHANNEL_PRIORITY", channel_priority)
    reset_context()

    # "bar" and its dependency "foo=2.0" were originally installed from "chan-b",
    # which is no longer part of the active channel list below.
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "foo", "2.0")
    _make_noarch_package(channel_b, "bar", "1.0", depends=("foo>=2",))

    # The only active channel, "chan-a", happens to also publish "foo", but only 1.0.
    chan_a = tmp_path / "chan-a"
    (chan_a / "noarch").mkdir(parents=True)
    (chan_a / "noarch" / "repodata.json").write_text(
        json.dumps(
            {
                "info": {"subdir": "noarch"},
                "packages": {
                    "foo-1.0-0.tar.bz2": {
                        "build": "0",
                        "build_number": 0,
                        "depends": [],
                        "constrains": [],
                        "md5": "0" * 32,
                        "name": "foo",
                        "noarch": "generic",
                        "sha256": "0" * 64,
                        "size": 1,
                        "subdir": "noarch",
                        "timestamp": 0,
                        "version": "1.0",
                    },
                    "foo-3.0-0.tar.bz2": {
                        "build": "0",
                        "build_number": 0,
                        "depends": [],
                        "constrains": [],
                        "md5": "0" * 32,
                        "name": "foo",
                        "noarch": "generic",
                        "sha256": "0" * 64,
                        "size": 1,
                        "subdir": "noarch",
                        "timestamp": 0,
                        "version": "3.0",
                    },
                },
                "packages.conda": {},
                "removed": [],
                "repodata_version": 1,
            }
        )
    )

    with tmp_env("--override-channels", f"--channel={channel_b}", "foo", "bar") as prefix:
        solver = Solver(
            prefix=prefix,
            channels=[Channel(str(chan_a))],
            subdirs=("noarch",),
        )
        solution = solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)
        packages = {pkg.name: pkg.version for pkg in solution}

        assert "foo" in packages
        assert packages["foo"] == "3.0"
        assert "bar" in packages
        assert packages["bar"] == "1.0"


@pytest.mark.xfail(
    reason="known issue: c-r-s will install packages from a new channel if available ",
    strict=True,
)
def test_channel_priority_updates_installed_dependency_two(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    tmp_env: TmpEnvFixture,
) -> None:
    """
    An active channel that publishes a newer `foo` must take precedence
    over the already-installed, `foo`. But should also try to minimize the
    change.
    """
    monkeypatch.setenv("CONDA_CHANNEL_PRIORITY", "strict")
    reset_context()

    # "bar" and its dependency "foo=2.0" were originally installed from "chan-b",
    # which is no longer part of the active channel list below.
    channel_b = tmp_path / "channel-b"
    _make_noarch_package(channel_b, "foo", "2.0")
    _make_noarch_package(channel_b, "bar", "1.0", depends=("foo>=2",))

    # The only active channel, "chan-a", happens to also publish "foo", but only 1.0.
    chan_a = tmp_path / "chan-a"
    (chan_a / "noarch").mkdir(parents=True)
    (chan_a / "noarch" / "repodata.json").write_text(
        json.dumps(
            {
                "info": {"subdir": "noarch"},
                "packages": {
                    "foo-1.0-0.tar.bz2": {
                        "build": "0",
                        "build_number": 0,
                        "depends": [],
                        "constrains": [],
                        "md5": "0" * 32,
                        "name": "foo",
                        "noarch": "generic",
                        "sha256": "0" * 64,
                        "size": 1,
                        "subdir": "noarch",
                        "timestamp": 0,
                        "version": "1.0",
                    },
                    "bar-3.0-0.tar.bz2": {
                        "build": "0",
                        "build_number": 0,
                        "depends": ["foo>=1"],
                        "constrains": [],
                        "md5": "0" * 32,
                        "name": "bar",
                        "noarch": "generic",
                        "sha256": "0" * 64,
                        "size": 1,
                        "subdir": "noarch",
                        "timestamp": 0,
                        "version": "3.0",
                    },
                },
                "packages.conda": {},
                "removed": [],
                "repodata_version": 1,
            }
        )
    )

    with tmp_env("--override-channels", f"--channel={channel_b}", "foo", "bar") as prefix:
        solver = Solver(
            prefix=prefix,
            channels=[Channel(str(chan_a))],
            subdirs=("noarch",),
        )
        solution = solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)
        packages = {pkg.name: pkg.version for pkg in solution}

        # Should keep the package foo==2 from chan_b, since it satisfies the requirements
        # of the updated package bar.
        assert "foo" in packages
        assert packages["foo"] == "2.0"
        assert "bar" in packages
        assert packages["bar"] == "3.0"


@pytest.mark.xfail(
    reason=(
        "known issue: c-r-s update semantics strictly require '>=' for each package that "
        "exists in the prefix. This causes Unsatisfiable errors when modifying channels. "
        "xref: https://github.com/conda/conda-rattler-solver/issues/135"
    ),
    strict=True,
)
@pytest.mark.usefixtures("solver_rattler")
def test_can_update_env_with_python(
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
) -> None:
    """
    Ensure that we can run an update when python is in the environment
    """

    with tmp_env("--override-channels", "--channel=defaults", "python") as prefix:
        out, err, exc = conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            "--channel=conda-forge",
            "--dry-run",
            "--json",
            "--all",
            raises=DryRunExit,
        )
        data = json.loads(out)
        assert data["success"] is True, err

def test_can_update_env_with_python(
    tmp_env: TmpEnvFixture,
    conda_cli: CondaCLIFixture,
) -> None:
    """
    Ensure that we can run an update when python is in the environment
    """

    with tmp_env("--override-channels", "--channel=defaults", "python", "--solver=rattler") as prefix:
        out, err, exc = conda_cli(
            "update",
            f"--prefix={prefix}",
            "--override-channels",
            "--channel=conda-forge",
            "--dry-run",
            "--json",
            "--all",
            "--solver=rattler",
            raises=DryRunExit,
        )
        data = json.loads(out)
        assert data["success"] is True, err
