# Copyright (C) 2022 Anaconda, Inc
# Copyright (C) 2023 conda
# SPDX-License-Identifier: BSD-3-Clause
import pytest
from conda.base.context import context

pytest_plugins = (
    # Add testing fixtures and internal pytest plugins here
    "conda.testing",
    "conda.testing.fixtures",
)


@pytest.fixture(autouse=True)
def _clear_cached_solver_backend():
    """
    Always clear conda's solver backend cache before and after each test.
    """
    context.plugin_manager.get_cached_solver_backend.cache_clear()
    yield
    context.plugin_manager.get_cached_solver_backend.cache_clear()
