"""Benchmark rattler vs libmamba solve times for comparable workloads.
See https://github.com/conda/conda-rattler-solver/issues/118.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conda.base.constants import UpdateModifier
from conda.base.context import context, reset_context
from conda.core.package_cache_data import PackageCacheData
from conda.core.subdir_data import SubdirData
from conda.exceptions import UnsatisfiableError

from conda_rattler_solver.exceptions import RattlerUnsatisfiableError

from .test_performance import _get_channels_from_lockfile
from .test_solver import _make_noarch_package

DATA = Path(__file__).parent / "data"

if TYPE_CHECKING:
    from conda.testing.fixtures import TmpEnvFixture
    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture


def _clear_memory_caches() -> None:
    SubdirData.clear_cached_local_channel_data(exclude_file=False)
    PackageCacheData.clear()


@pytest.mark.benchmark
@pytest.mark.parametrize("solver_name", ["rattler", "libmamba"])
def test_solve_update_all_small_local_channel(
    benchmark: BenchmarkFixture,
    tmp_env: TmpEnvFixture,
    monkeypatch: MonkeyPatch,
    solver_name: str,
) -> None:
    """Small workload: update --all on a tiny local-channel env."""
    monkeypatch.setenv("CONDA_SOLVER", solver_name)
    reset_context()
    assert context.solver == solver_name

    channel = DATA / "mamba_repo"
    with tmp_env("test-package", "--channel", str(channel)) as prefix:
        SolverBackend = context.plugin_manager.get_cached_solver_backend()
        solver = SolverBackend(
            prefix=prefix,
            channels=[str(channel)],
            command="update",
        )

        def run():
            return solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)

        solution = benchmark(run)
        assert "test-package" in {rec.name for rec in solution}


@pytest.mark.benchmark
@pytest.mark.parametrize("solver_name", ["rattler", "libmamba"])
def test_solve_update_all_medium_lockfile(
    tmp_env: TmpEnvFixture,
    monkeypatch: MonkeyPatch,
    benchmark: BenchmarkFixture,
    solver_name: str,
):
    """Medium workload: update --all on a scipipe lockfile env."""
    monkeypatch.setenv("CONDA_SOLVER", solver_name)
    reset_context()
    assert context.solver == solver_name

    lockfile = DATA / f"scipipe.{context.subdir}.lock"

    if not lockfile.exists():
        pytest.skip(f"no lockfile for {context.subdir}")

    channels = _get_channels_from_lockfile(lockfile)

    with tmp_env("--file", lockfile) as prefix:
        SolverBackend = context.plugin_manager.get_cached_solver_backend()
        solver = SolverBackend(
            prefix=prefix,
            channels=channels,
            command="update",
        )

        def run():
            return solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)

        solution = benchmark(run)
        assert solution


@pytest.mark.benchmark
@pytest.mark.parametrize("solver_name", ["rattler", "libmamba"])
def test_solve_update_all_large_lockfile(
    tmp_env: TmpEnvFixture,
    monkeypatch: MonkeyPatch,
    benchmark: BenchmarkFixture,
    solver_name: str,
):
    """Large workload: update --all on a pangeo lockfile env (linux-64 only)."""
    monkeypatch.setenv("CONDA_SOLVER", solver_name)
    reset_context()
    assert context.solver == solver_name

    lockfile = DATA / "pangeo_ml_notebook.linux-64.lock"

    if context.subdir != "linux-64":
        pytest.skip("large lockfile is linux-64 only")

    channels = _get_channels_from_lockfile(lockfile)

    with tmp_env("--file", lockfile) as prefix:
        SolverBackend = context.plugin_manager.get_cached_solver_backend()
        solver = SolverBackend(
            prefix=prefix,
            channels=channels,
            command="update",
        )

        def run():
            return solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)

        solution = benchmark(run)
        assert solution


@pytest.mark.benchmark
@pytest.mark.parametrize("solver_name", ["rattler", "libmamba"])
def test_solve_conflict_small_local_channel(
    benchmark,
    tmp_env,
    tmp_path,
    monkeypatch,
    solver_name,
):
    """Small conflict: time unsatisfiable install on a tiny local-channel env."""
    monkeypatch.setenv("CONDA_SOLVER", solver_name)
    reset_context()
    assert context.solver == solver_name

    channel = tmp_path / "conflict_repo"
    _make_noarch_package(channel, "bar", "1.0")
    _make_noarch_package(channel, "bar", "2.0")
    _make_noarch_package(channel, "foo", "1.0", depends=("bar=1",))
    _make_noarch_package(channel, "boz", "1.0", depends=("bar=2",))

    with tmp_env(
        "foo",
        "--override-channels",
        "--channel",
        str(channel),
    ) as prefix:
        SolverBackend = context.plugin_manager.get_cached_solver_backend()
        solver = SolverBackend(
            prefix=prefix,
            channels=[str(channel)],
            specs_to_add=["boz"],
            command="install",
        )

        def run():
            with pytest.raises((UnsatisfiableError, RattlerUnsatisfiableError)):
                solver.solve_final_state()

        benchmark(run)


@pytest.mark.benchmark
@pytest.mark.parametrize("solver_name", ["rattler", "libmamba"])
@pytest.mark.parametrize("cache_state", ["cold", "warm"])
def test_solve_update_all_medium_lockfile_cache(
    benchmark: BenchmarkFixture,
    tmp_env: TmpEnvFixture,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    solver_name: str,
    cache_state: str,
) -> None:
    """Medium update --all with cold (empty cache) vs warm (filled cache)."""
    monkeypatch.setenv("CONDA_SOLVER", solver_name)
    pkgs = tmp_path / "pkgs"
    pkgs.mkdir()
    monkeypatch.setenv("CONDA_PKGS_DIRS", str(pkgs))
    reset_context()
    assert context.solver == solver_name

    lockfile = DATA / f"scipipe.{context.subdir}.lock"
    if not lockfile.exists():
        pytest.skip(f"no lockfile for {context.subdir}")

    channels = _get_channels_from_lockfile(lockfile)

    with tmp_env("--file", lockfile) as prefix:
        SolverBackend = context.plugin_manager.get_cached_solver_backend()
        solver = SolverBackend(
            prefix=prefix,
            channels=channels,
            command="update",
        )

        def run():
            return solver.solve_final_state(update_modifier=UpdateModifier.UPDATE_ALL)

        if cache_state == "warm":
            run()  # Fill up cache to create a "warm" state
            solution = benchmark(run)
            assert solution
        else:
            # For true cold on each round, wipe on-disk pkgs cache + memory before each iteration
            def setup_cold():
                shutil.rmtree(pkgs, ignore_errors=True)
                pkgs.mkdir(parents=True, exist_ok=True)
                _clear_memory_caches()

            solution = benchmark.pedantic(
                run,
                setup=setup_cold,
                rounds=5,
                iterations=1,
            )
            assert solution
