# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from conda.base.constants import UpdateModifier
from conda.models.enums import PackageType
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord, PrefixRecord

from conda_rattler_solver.solver import RattlerSolver
from conda_rattler_solver.state import SolverInputState, SolverOutputState


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
