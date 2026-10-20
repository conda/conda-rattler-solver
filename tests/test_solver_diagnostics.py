# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import pytest
from conda.core.prefix_data import PrefixData
from conda.exceptions import PackagesNotFoundError
from conda.models.match_spec import MatchSpec
from conda.models.records import PrefixRecord

from conda_rattler_solver.exceptions import RattlerUnsatisfiableError
from conda_rattler_solver.solver import RattlerSolver
from conda_rattler_solver.state import SolverInputState, SolverOutputState

DIAGNOSTICS = (
    pytest.param("No candidates were found for {}.", id="standalone"),
    pytest.param("{}, for which no candidates were found.", id="nested"),
)


def _record(name):
    return PrefixRecord(
        name=name,
        version="2.0",
        build="build_0",
        build_number=0,
        channel="https://example.test/available",
        subdir="noarch",
        fn=f"{name}-2.0-build_0.conda",
    )


@pytest.fixture
def diagnostic_state(tmp_path):
    solver = RattlerSolver(tmp_path, channels=(), subdirs=("noarch",))
    PrefixData(tmp_path)._prefix_records.update(
        (name, _record(name)) for name in ("other-a", "other-b", "target")
    )
    in_state = SolverInputState(tmp_path)
    out_state = SolverOutputState(solver_input_state=in_state)
    return solver, in_state, out_state


@pytest.mark.parametrize("diagnostic", DIAGNOSTICS)
@pytest.mark.parametrize(
    "spec, matches, name",
    (
        pytest.param("target >=2", True, "target", id="version-match"),
        pytest.param("target >=3", False, "target", id="version-mismatch"),
        pytest.param("target >=2 build_0", True, "target", id="build-match"),
        pytest.param("target >=2 build_1", False, "target", id="build-mismatch"),
        pytest.param(
            "https://example.test/available::target >=2", True, "target", id="channel-match"
        ),
        pytest.param(
            "https://example.test/missing::target >=2", False, "target", id="channel-mismatch"
        ),
        pytest.param("absent >=2", False, "absent", id="absent-name"),
        pytest.param("tar* >=2", True, "*", id="wildcard-match"),
        pytest.param("tar* >=3", False, "*", id="wildcard-mismatch"),
        pytest.param("^tar.*$ >=2", True, "*", id="regex-match"),
        pytest.param("* >=2", True, "*", id="any-name"),
        pytest.param("target[cli] >=2", True, "target", id="extras"),
    ),
)
def test_missing_candidate_diagnostics_preserve_matching(
    diagnostic_state, diagnostic, spec, matches, name
):
    solver, in_state, out_state = diagnostic_state
    problems = diagnostic.format(spec)

    if matches:
        solver._maybe_raise_for_problems(problems, in_state, out_state)

        assert set(out_state.conflicts) == {name}
        assert out_state.conflicts[name].match(in_state.installed["target"])

        with pytest.raises(RattlerUnsatisfiableError) as exc_info:
            solver._maybe_raise_for_problems(problems, in_state, out_state)
        assert exc_info.value.allow_retry is False
    else:
        with pytest.raises(PackagesNotFoundError) as exc_info:
            solver._maybe_raise_for_problems(problems, in_state, out_state)
        assert exc_info.value.allow_retry is False
        assert len(exc_info.value.packages) == 1
        assert out_state.conflicts == {}


@pytest.mark.parametrize("diagnostic", DIAGNOSTICS)
@pytest.mark.parametrize("name", ("target", "absent"))
def test_exact_name_diagnostics_avoid_unrelated_record_matches(
    diagnostic_state, diagnostic, name, monkeypatch
):
    solver, in_state, out_state = diagnostic_state
    compared = []
    match = MatchSpec.match

    def track_match(self, record):
        compared.append(record.name)
        return match(self, record)

    monkeypatch.setattr(MatchSpec, "match", track_match)
    problems = diagnostic.format(f"{name} >=2")
    if name == "absent":
        with pytest.raises(PackagesNotFoundError):
            solver._maybe_raise_for_problems(problems, in_state, out_state)
        assert compared == []
    else:
        solver._maybe_raise_for_problems(problems, in_state, out_state)
        assert compared == ["target"]


@pytest.mark.benchmark
@pytest.mark.parametrize("installed_count", (100, 5000))
@pytest.mark.parametrize("diagnostic", DIAGNOSTICS)
def test_benchmark_missing_candidate_diagnostics(tmp_path, benchmark, installed_count, diagnostic):
    solver = RattlerSolver(tmp_path, channels=(), subdirs=("noarch",))
    PrefixData(tmp_path)._prefix_records.update(
        (name, _record(name)) for name in (f"package-{i:05d}" for i in range(installed_count))
    )
    in_state = SolverInputState(tmp_path)
    # Diagnose eight records at the end of the installed package order.
    names = tuple(f"package-{i:05d}" for i in range(installed_count - 8, installed_count))
    problems = "\n".join(diagnostic.format(f"{name} >=2") for name in names)
    out_state = SolverOutputState(solver_input_state=in_state)

    def setup():
        out_state.conflicts.clear()
        return (problems, in_state, out_state), {}

    benchmark.pedantic(
        solver._maybe_raise_for_problems,
        setup=setup,
        rounds=7,
        warmup_rounds=2,
        iterations=1,
    )

    assert set(out_state.conflicts) == set(names)
