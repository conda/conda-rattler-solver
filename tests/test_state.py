from __future__ import annotations

import pytest
from conda.models.records import PackageRecord

import conda_rattler_solver.state as state_module
from conda_rattler_solver.state import SolverInputState


@pytest.mark.parametrize(
    ("virtual_packages", "expected"),
    [
        pytest.param((), {}, id="empty"),
        pytest.param(
            (
                PackageRecord(
                    name="__test",
                    version="2",
                    build="provided",
                    build_number=0,
                ),
            ),
            {"__test": ("2", "provided")},
            id="provided",
        ),
    ],
)
def test_solver_input_state_uses_provided_virtual_packages(
    monkeypatch,
    tmp_path,
    virtual_packages,
    expected,
):
    monkeypatch.setattr(
        state_module,
        "Index",
        lambda: pytest.fail("local virtual packages must not be detected"),
    )

    state = SolverInputState(tmp_path, virtual_packages=virtual_packages)

    assert {
        name: (record.version, record.build) for name, record in state.virtual.items()
    } == expected
