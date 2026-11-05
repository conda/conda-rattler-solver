# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Check sampling through pytest-benchmark and the normal conda fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("rounds", [None, 12], ids=["default", "requested"])
def test_state_benchmarks_use_requested_rounds(tmp_path: Path, rounds: int | None) -> None:
    repository = Path(__file__).parents[1]
    results = tmp_path / "measurements.json"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_state_benchmarks.py",
        "--benchmark-only",
        "--benchmark-json",
        str(results),
        "--basetemp",
        str(tmp_path / "pytest"),
        "-q",
    ]
    if rounds is not None:
        command += ["--benchmark-min-rounds", str(rounds)]
    environment = dict(os.environ)
    # Do not inherit an outer pytest invocation's marker or benchmark options.
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        command, cwd=repository, env=environment, text=True, capture_output=True, timeout=120
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    measurements = json.loads(results.read_text())["benchmarks"]
    assert len(measurements) == 7
    assert {case["stats"]["rounds"] for case in measurements} == {rounds or 5}
    assert {case["stats"]["iterations"] for case in measurements} == {1}
