# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import pytest
from conda.base.constants import UpdateModifier
from conda.base.context import context
from conda.core.prefix_data import PrefixData
from conda.models.enums import PackageType
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord, PrefixRecord

from conda_rattler_solver.solver import RattlerSolver
from conda_rattler_solver.state import SolverInputState, SolverOutputState


def test_update_all_includes_python_in_always_update(tmp_path):
    records = PrefixData(tmp_path)._prefix_records
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

    state = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)

    assert "python" in state.always_update
    assert "numpy" in state.always_update


def test_update_all_emits_installed_version_constraint(tmp_path):
    PrefixData(tmp_path)._prefix_records["libmamba"] = PrefixRecord(
        name="libmamba",
        version="2.3.2",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="libmamba-2.3.2-0.conda",
    )
    in_state = SolverInputState(
        tmp_path,
        update_modifier=UpdateModifier.UPDATE_ALL,
        command="update",
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
        PrefixData(prefix)._prefix_records["libmamba"] = PrefixRecord(
            name="libmamba",
            version="2.3.2",
            build="0",
            build_number=0,
            channel="conda-forge",
            subdir="noarch",
            fn="libmamba-2.3.2-0.conda",
            package_type=package_type,
        )
        in_state = SolverInputState(
            prefix,
            requested=("libmamba",),
            command=command,
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
    PrefixData(tmp_path)._prefix_records["python"] = PrefixRecord(
        name="python",
        version="3.13.9",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="python-3.13.9-0.conda",
    )
    in_state = SolverInputState(
        tmp_path,
        update_modifier=UpdateModifier.UPDATE_ALL,
        command="update",
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
    PrefixData(tmp_path)._prefix_records["python"] = PrefixRecord(
        name="python",
        version="3.13.9",
        build="0",
        build_number=0,
        channel="conda-forge",
        subdir="noarch",
        fn="python-3.13.9-0.conda",
    )
    in_state = SolverInputState(
        tmp_path,
        requested=("python=3.14",),
        update_modifier=UpdateModifier.UPDATE_SPECS,
        command="install",
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


def test_rebuilt_outputs_reuse_record_specs(tmp_path, monkeypatch):
    records = PrefixData(tmp_path)._prefix_records
    records.update({name: _record(name) for name in ("alpha", "beta")})
    conversions = []
    original = PackageRecord.to_match_spec

    def to_match_spec(record):
        conversions.append(record.name)
        return original(record)

    monkeypatch.setattr(PackageRecord, "to_match_spec", to_match_spec)
    state = SolverInputState(tmp_path)
    assert not conversions
    first = SolverOutputState(solver_input_state=state)
    expected = dict(first.specs)
    first_conversions = tuple(conversions)
    assert {"alpha", "beta"} <= set(first_conversions)
    retry = SolverOutputState(
        solver_input_state=state,
        records={"alpha": _record("alpha", "2.0")},
        conflicts={"alpha": MatchSpec("alpha")},
    )

    assert retry.specs == expected
    assert tuple(conversions) == first_conversions


def test_auto_update_policy_is_captured_before_first_read(tmp_path):
    with context._override("_root_prefix", str(tmp_path)):
        with context._override("auto_update_conda", True):
            first = SolverInputState(tmp_path)
        with context._override("auto_update_conda", False):
            second = SolverInputState(tmp_path)
            assert "conda" in first.always_update
            assert "conda" not in second.always_update


def _write_history(prefix, specs):
    metadata = prefix / "conda-meta"
    metadata.mkdir(parents=True, exist_ok=True)
    (metadata / "history").write_text(
        f"==> 2026-01-01 00:00:00 <==\n# cmd: conda install\n# update specs: {list(specs)!r}\n"
    )


def test_new_input_state_refreshes_prefix_pins_and_history(tmp_path):
    prefix_data = PrefixData(tmp_path)
    original = _record("alpha")
    prefix_data._prefix_records["alpha"] = original
    _write_history(tmp_path, ("alpha =1",))
    pinned_file = tmp_path / "conda-meta" / "pinned"
    pinned_file.write_text("alpha <2\n")
    first = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)

    replacement = _record("alpha", "2.0")
    prefix_data._prefix_records.update(alpha=replacement, beta=_record("beta"))
    _write_history(tmp_path, ("alpha >=2", "beta"))
    pinned_file.write_text("alpha >=2\n")
    second = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL)
    unpinned = SolverInputState(
        tmp_path, update_modifier=UpdateModifier.UPDATE_ALL, ignore_pinned=True
    )

    # First access must still describe the prefix and policy seen at construction.
    assert first.installed["alpha"] is original
    assert "beta" not in first.installed
    assert first.history == {"alpha": MatchSpec("alpha =1")}
    assert first.pinned == {"alpha": MatchSpec("alpha <2", optional=True)}
    assert "alpha" not in first.always_update
    assert SolverOutputState(solver_input_state=first).specs["alpha"] == MatchSpec(
        "alpha <2", optional=True
    )
    assert second.installed["alpha"] is replacement
    assert "beta" in second.installed
    assert second.history == {"alpha": MatchSpec("alpha >=2"), "beta": MatchSpec("beta")}
    assert second.pinned == {"alpha": MatchSpec("alpha >=2", optional=True)}
    assert "alpha" not in second.always_update
    assert {"alpha", "beta"} <= unpinned.always_update.keys()
    assert not unpinned.pinned


def test_cached_specs_preserve_source_precedence(tmp_path):
    names = ("alpha", "beta", "gamma", "delta", "epsilon")
    PrefixData(tmp_path)._prefix_records.update({name: _record(name) for name in names})
    _write_history(tmp_path, ("alpha =1", "beta =1", "gamma =1"))
    (tmp_path / "conda-meta" / "pinned").write_text("alpha <3\nbeta <3\n")
    with context._override("_aggressive_update_packages", names[:4]):
        state = SolverInputState(tmp_path, requested=("alpha >=2",))
    output = SolverOutputState(solver_input_state=state)

    assert output.specs["alpha"] == MatchSpec("alpha >=2")
    assert output.specs["beta"] == MatchSpec("beta <3", optional=True)
    assert output.specs["gamma"] == MatchSpec("gamma =1")
    assert output.specs["delta"] == MatchSpec("delta")
    assert output.specs["epsilon"].match(state.installed["epsilon"])
    assert tuple(output.specs)[:5] == names
    assert set(state.virtual) <= output.specs.keys()
    assert set(state.always_update) == set(names[:4])
    assert state.always_update is state.always_update


def test_virtual_override_before_first_read_is_a_sorted_snapshot(tmp_path):
    state = SolverInputState(tmp_path)
    replacements = {name: _record(name) for name in ("__zeta", "__alpha")}
    # Callers currently provide virtual packages after construction, as described in #105.
    state._virtual = replacements
    virtual = state.virtual

    assert tuple(virtual) == ("__alpha", "__zeta")
    with pytest.raises(TypeError):
        virtual["__other"] = _record("__other")
    replacements["__later"] = _record("__later")
    assert "__later" not in state.virtual
    output = SolverOutputState(solver_input_state=state)
    assert tuple(output.virtual_specs) == ("__alpha", "__zeta")
    assert all(output.specs[name].match(record) for name, record in virtual.items())


def test_cached_specs_are_read_only(tmp_path):
    state = SolverInputState(tmp_path, requested=("alpha",))
    output = SolverOutputState(solver_input_state=state)

    with pytest.raises(TypeError):
        output.specs["beta"] = MatchSpec("beta")
    assert "beta" not in output.specs


@pytest.mark.parametrize(
    "property_name",
    (
        "installed",
        "history",
        "pinned",
        "virtual",
        "aggressive_updates",
        "always_update",
        "requested",
        "do_not_remove",
    ),
)
def test_input_mappings_are_read_only(tmp_path, property_name):
    state = SolverInputState(tmp_path)
    with pytest.raises(TypeError):
        getattr(state, property_name)["alpha"] = MatchSpec("alpha")


def test_cached_inputs_do_not_freeze_output_records_or_history(tmp_path):
    original = _record("alpha")
    PrefixData(tmp_path)._prefix_records["alpha"] = original
    state = SolverInputState(tmp_path, requested=("alpha",))
    output = SolverOutputState(solver_input_state=state)
    initial_specs = dict(output.specs)
    assert tuple(output.current_solution) == (original,)
    replacement = _record("alpha", "2.0")
    output.records["alpha"] = replacement
    output.for_history["beta"] = MatchSpec("beta")

    assert tuple(output.current_solution) == (replacement,)
    assert output.for_history["beta"] == MatchSpec("beta")
    assert state.installed["alpha"] is original
    assert "beta" not in state.requested
    assert output.specs == initial_specs


def test_cached_inputs_do_not_freeze_retry_conflicts(tmp_path):
    PrefixData(tmp_path)._prefix_records.update(
        alpha=_record("alpha"), python=_record("python", "3.13.9")
    )
    state = SolverInputState(tmp_path, update_modifier=UpdateModifier.UPDATE_ALL, command="update")
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


def test_cached_inputs_do_not_freeze_prune(tmp_path):
    PrefixData(tmp_path)._prefix_records["alpha"] = _record("alpha")
    state = SolverInputState(tmp_path, prune=True)
    output = SolverOutputState(solver_input_state=state)
    solver = RattlerSolver(tmp_path, channels=())
    pruned = solver._collect_specs_main(state, output)
    assert not pruned["locked_packages"]
    assert not pruned["pinned_packages"]

    # UPDATE_DEPS disables pruning after its recursive solve.
    state._prune = False
    unpruned = solver._collect_specs_main(state, output)

    assert unpruned["locked_packages"] or unpruned["pinned_packages"]
