# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import pytest
from conda.base.constants import UpdateModifier
from conda.base.context import context
from conda.models.enums import PackageType
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord, PrefixRecord

from conda_rattler_solver.solver import RattlerSolver
from conda_rattler_solver.state import SolverInputState, SolverOutputState


def _record(name, version="1.0"):
    return PrefixRecord(
        name=name,
        version=version,
        build="0",
        build_number=0,
        channel="https://example.invalid",
        subdir="noarch",
        fn=f"{name}-{version}-0.conda",
        url=f"https://example.invalid/noarch/{name}-{version}-0.conda",
    )


def test_retries_reuse_input_views(tmp_path):
    state = SolverInputState(
        tmp_path, requested=("alpha >=2",), update_modifier=UpdateModifier.UPDATE_ALL
    )
    record = _record("alpha")
    state.prefix_data._prefix_records["alpha"] = record
    state._pinned = {"alpha": MatchSpec("alpha <3")}
    state._history = {"alpha": MatchSpec("alpha =1")}
    first = SolverOutputState(solver_input_state=state)
    views = state.installed, state.virtual, state.always_update, first.specs
    retry = SolverOutputState(
        solver_input_state=state,
        records={"alpha": _record("alpha", "2.0")},
        conflicts={"alpha": MatchSpec("alpha")},
        for_history={"beta": MatchSpec("beta")},
    )

    assert state.installed["alpha"] is record
    assert retry.specs["alpha"] == MatchSpec("alpha >=2")
    assert "beta" not in retry.specs
    assert "alpha" not in state.always_update
    assert all(
        before is after
        for before, after in zip(
            views, (state.installed, state.virtual, state.always_update, retry.specs)
        )
    )


def test_cached_specs_are_read_only(tmp_path):
    state = SolverInputState(tmp_path, requested=("alpha",))
    output = SolverOutputState(solver_input_state=state)

    with pytest.raises(TypeError):
        output.specs["beta"] = MatchSpec("beta")
    assert "beta" not in output.specs


def test_new_input_state_refreshes_installed_records_and_pins(tmp_path):
    with context._override("pinned_packages", ("alpha <2",)):
        first = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)
        old = _record("alpha")
        first.prefix_data._prefix_records["alpha"] = old
        output = SolverOutputState(solver_input_state=first)
        assert output.specs["alpha"].get_raw_value("version") == "<2"
        assert "alpha" not in first.always_update

    replacement = _record("alpha", "2.0")
    first.prefix_data._prefix_records["alpha"] = replacement
    first.prefix_data._prefix_records["beta"] = _record("beta")
    with context._override("pinned_packages", ("alpha >=2",)):
        pinned = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)
        pinned_output = SolverOutputState(solver_input_state=pinned)
        assert pinned_output.specs["alpha"].get_raw_value("version") == ">=2"
        assert "alpha" not in pinned.always_update
        second = SolverInputState(
            tmp_path, update_modifier=UpdateModifier.UPDATE_ALL, ignore_pinned=True
        )
        next_output = SolverOutputState(solver_input_state=second)
        assert second.installed["alpha"] is replacement
        assert {"alpha", "beta"} <= second.always_update.keys()
        assert next_output.specs["alpha"].match(replacement)
        assert "beta" in next_output.specs

    assert first.installed["alpha"] is old
    assert "beta" not in first.installed
    assert output.specs["alpha"].get_raw_value("version") == "<2"


def test_new_input_state_refreshes_auto_update_conda(tmp_path):
    with context._override("auto_update_conda", True):
        first = SolverInputState(tmp_path)
        first.prefix = context.root_prefix
        assert "conda" in first.always_update
    with context._override("auto_update_conda", False):
        second = SolverInputState(tmp_path)
        second.prefix = context.root_prefix
        assert "conda" not in second.always_update
        assert "conda" in first.always_update


def test_cached_input_does_not_freeze_retry_conflicts(tmp_path):
    state = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL, command="update")
    state.prefix_data._prefix_records["alpha"] = _record("alpha")
    state.prefix_data._prefix_records["python"] = _record("python", "3.13.9")
    solver = RattlerSolver(tmp_path, channels=(), command="update")
    output = SolverOutputState(solver_input_state=state)

    first = solver._collect_specs_main(state, output)
    assert "alpha" in {str(spec) for spec in first["specs"]}
    assert "alpha >=1.0" in {str(spec) for spec in first["constraints"]}
    output.conflicts["alpha"] = MatchSpec("alpha")
    retry = solver._collect_specs_main(state, output)
    assert "alpha" not in {str(spec) for spec in retry["specs"]}
    assert "alpha >=1.0" not in {str(spec) for spec in retry["constraints"]}
    assert "python 3.13.*" in {str(spec) for spec in retry["constraints"]}


@pytest.mark.benchmark
@pytest.mark.parametrize("reuse_input", (False, True), ids=("first-attempt", "retry"))
def test_update_all_spec_collection_benchmark(tmp_path, benchmark, reuse_input):
    names = {f"package-{i:04}" for i in range(563)}
    initial = SolverInputState(tmp_path)
    initial.prefix_data._prefix_records.update({name: _record(name) for name in names})
    solver = RattlerSolver(tmp_path, channels=(), command="update")

    def prepare():
        state = SolverInputState(
            tmp_path, update_modifier=UpdateModifier.UPDATE_ALL, command="update"
        )
        return (state, SolverOutputState(solver_input_state=state)), {}

    if reuse_input:
        args, _ = prepare()
        solver._collect_specs_main(*args)
        result = benchmark.pedantic(solver._collect_specs_main, args=args, rounds=5)
    else:
        result = benchmark.pedantic(solver._collect_specs_main, setup=prepare, rounds=5)

    assert {str(spec) for spec in result["specs"]} == names
    assert {str(spec) for spec in result["constraints"]} == {f"{name} >=1.0" for name in names}


def test_update_all_includes_python_in_always_update(tmp_path):
    state = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)
    records = state.prefix_data._prefix_records
    records["python"] = PrefixRecord(
        name="python",
        version="3.13.9",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="python-3.13.9-0.conda",
    )
    records["numpy"] = PrefixRecord(
        name="numpy",
        version="2.0.0",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="numpy-2.0.0-0.conda",
    )

    assert "python" in state.always_update
    assert "numpy" in state.always_update


def test_update_all_emits_installed_version_constraint(tmp_path):
    in_state = SolverInputState(
        tmp_path,
        update_modifier=UpdateModifier.UPDATE_ALL,
        command="update",
    )
    in_state.prefix_data._prefix_records["libmamba"] = PrefixRecord(
        name="libmamba",
        version="2.3.2",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="libmamba-2.3.2-0.conda",
    )
    out_state = SolverOutputState(solver_input_state=in_state)
    solver = RattlerSolver(tmp_path, channels=("defaults",), command="update")

    collected = solver._collect_specs_main(in_state, out_state)
    specs = [str(spec) for spec in collected["specs"]]
    constraints = [str(spec) for spec in collected["constraints"]]

    assert "libmamba" in specs
    assert "libmamba >=2.3.2" in constraints


def test_installed_version_constraint_exclusions(tmp_path):
    for command, package_type in (
        ("install", None),
        ("update", PackageType.VIRTUAL_PYTHON_EGG_UNMANAGEABLE),
    ):
        prefix = tmp_path / command
        in_state = SolverInputState(
            prefix,
            requested=("libmamba",),
            command=command,
        )
        in_state.prefix_data._prefix_records["libmamba"] = PrefixRecord(
            name="libmamba",
            version="2.3.2",
            build="0",
            build_number=0,
            channel="conda-forge",
            subdir="noarch",
            fn="libmamba-2.3.2-0.conda",
            package_type=package_type,
        )
        out_state = SolverOutputState(solver_input_state=in_state)
        solver = RattlerSolver(
            prefix,
            channels=("defaults",),
            specs_to_add=("libmamba",),
            command=command,
        )

        collected = solver._collect_specs_main(in_state, out_state)
        constraints = [str(spec) for spec in collected["constraints"]]

        assert "libmamba >=2.3.2" not in constraints


def test_update_all_emits_python_constraint_and_update_spec(tmp_path):
    """UPDATE_ALL must request python while constraining to the current major.minor.

    That combination allows patch upgrades (3.13.9 → 3.13.14) and blocks minor jumps
    (3.13 → 3.14) unless python is requested explicitly.
    """
    in_state = SolverInputState(
        tmp_path,
        update_modifier=UpdateModifier.UPDATE_ALL,
        command="update",
    )
    in_state.prefix_data._prefix_records["python"] = PrefixRecord(
        name="python",
        version="3.13.9",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="python-3.13.9-0.conda",
    )
    out_state = SolverOutputState(solver_input_state=in_state)
    solver = RattlerSolver(tmp_path, channels=("defaults",), command="update")

    collected = solver._collect_specs_main(in_state, out_state)
    specs = [str(spec) for spec in collected["specs"]]
    constraints = [str(spec) for spec in collected["constraints"]]

    assert "python" in in_state.always_update
    assert "python" in specs
    assert "python 3.13.*" in constraints

    pin = MatchSpec("python 3.13.*")
    assert pin.match(
        PackageRecord(
            name="python",
            version="3.13.14",
            build="0",
            build_number=0,
            channel="conda-forge",
            subdir="noarch",
            fn="python-3.13.14-0.conda",
        )
    )
    assert not pin.match(
        PackageRecord(
            name="python",
            version="3.14.0",
            build="0",
            build_number=0,
            channel="conda-forge",
            subdir="noarch",
            fn="python-3.14.0-0.conda",
        )
    )


def test_explicit_python_request_skips_major_minor_constraint(tmp_path):
    """Explicit python on the CLI must not get the implicit X.Y.* constraint."""
    in_state = SolverInputState(
        tmp_path,
        requested=("python=3.14",),
        update_modifier=UpdateModifier.UPDATE_SPECS,
        command="install",
    )
    in_state.prefix_data._prefix_records["python"] = PrefixRecord(
        name="python",
        version="3.13.9",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="python-3.13.9-0.conda",
    )
    out_state = SolverOutputState(solver_input_state=in_state)
    solver = RattlerSolver(
        tmp_path,
        channels=("defaults",),
        specs_to_add=("python=3.14",),
        command="install",
    )

    collected = solver._collect_specs_main(in_state, out_state)
    constraints = [str(spec) for spec in collected["constraints"]]

    assert "python 3.13.*" not in constraints
    assert not any("3.13.*" in c for c in constraints)
