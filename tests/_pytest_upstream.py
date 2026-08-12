"""Pytest plugin for expected failures in conda's upstream suite under rattler.

Loaded only when CRS CI runs conda's tests (copied to conda's ``tests/`` and
loaded via ``-p tests._pytest_upstream`` in ``.github/workflows/tests.yml``).
Use ``strict=True`` so an unexpected pass (XPASS) fails the job once the bug is fixed.
"""

from __future__ import annotations

import pytest

_XFAILS = {
    "tests/test_create.py::test_dont_remove_conda_dependency_with_dependent_packages[rattler]": (
        "Installed packages missing from narrowed channels: "
        "https://github.com/conda/conda-rattler-solver/issues/88"
    ),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if reason := _XFAILS.get(item.nodeid):
            item.add_marker(pytest.mark.xfail(reason=reason, strict=True))
