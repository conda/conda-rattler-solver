# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
import os
from pathlib import Path

import pytest
from conda.base.context import context

pytest_plugins = (
    # Add testing fixtures and internal pytest plugins here
    "conda.testing",
    "conda.testing.fixtures",
)


@pytest.fixture
def isolated_condarc_env(tmp_path: Path) -> dict[str, str]:
    """Subprocess environment with condarc discovery isolated to `tmp_path`."""
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),  # Windows config discovery
        "CONDARC": str(tmp_path / ".condarc"),
        "CONDA_PKGS_DIRS": str(tmp_path / "pkgs"),
    }
    env.pop("CONDA_CHANNELS", None)
    return env


@pytest.fixture(autouse=True)
def _clear_cached_solver_backend():
    """
    Always clear conda's solver backend cache before and after each test.
    """
    context.plugin_manager.get_cached_solver_backend.cache_clear()
    yield
    context.plugin_manager.get_cached_solver_backend.cache_clear()
