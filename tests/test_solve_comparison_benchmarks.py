"""Benchmark rattler vs libmamba solve times for comparable workloads.
See https://github.com/conda/conda-rattler-solver/issues/118.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conda.base.constants import UpdateModifier
from conda.base.context import context, reset_context

from .test_performance import _get_channels_from_lockfile

DATA = Path(__file__).parent / "data"

if TYPE_CHECKING:
    from conda.testing.fixtures import TmpEnvFixture
    from pytest import MonkeyPatch
    from pytest_benchmark.fixture import BenchmarkFixture


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
