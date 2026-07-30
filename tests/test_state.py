# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from conda.base.constants import UpdateModifier
from conda.models.records import PrefixRecord

from conda_rattler_solver.state import SolverInputState


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
