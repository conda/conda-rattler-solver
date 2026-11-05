# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Run real pytest benchmarks in disposable repositories to test orchestration."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BENCHMARK = """\
import os
from pathlib import Path

import pytest


@pytest.mark.benchmark
def test_source(benchmark):
    assert Path("tests/harness.txt").read_text() == "head harness"
    assert Path("pyproject.toml").read_text().endswith("# head configuration\\n")
    assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
    assert Path(os.environ["PYTHONPYCACHEPREFIX"]).is_absolute()
    assert benchmark.pedantic(lambda: sum(range(10)), rounds=2) == 45
    assert os.environ.get("FAIL_REVISION") != Path("source.txt").read_text()
"""
HOOK = """\
import os
import sys
from pathlib import Path


def pytest_benchmark_update_json(config, benchmarks, output_json):
    revision = Path("source.txt").read_text()
    output_json["fixture"] = {"revision": revision, "python": sys.executable,
                              "pycache": os.environ["PYTHONPYCACHEPREFIX"]}
    if os.environ.get("WRONG_SHA_REVISION") == revision:
        output_json["commit_info"]["id"] = "0" * 40
"""


@pytest.fixture
def runner(tmp_path, monkeypatch):
    # Defer developer-tool imports until execution, so the head tests also collect
    # against base revisions that do not contain these modules.
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "dev"))
    import run_benchmarks

    repository = tmp_path / "repository"
    repository.mkdir()
    monkeypatch.chdir(repository)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTEST_PLUGINS", "pytest_benchmark.plugin")
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    git = run_benchmarks.git
    git("init", "-q")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Benchmark fixture")
    git("config", "core.autocrlf", "false")
    git("config", "commit.gpgsign", "false")
    (repository / "tests").mkdir()
    (repository / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n")
    (repository / "tests/test_state_benchmarks.py").write_text(BENCHMARK)
    (repository / "tests/conftest.py").write_text(HOOK)
    commits = {}
    for revision in ("base", "head"):
        obsolete = repository / "obsolete.txt"
        if revision == "base":
            obsolete.write_text("old tracked file")
        else:
            obsolete.unlink()
        (repository / "source.txt").write_text(revision)
        (repository / "tests/harness.txt").write_text(f"{revision} harness")
        (repository / "pyproject.toml").write_text(
            '[tool.pytest.ini_options]\nmarkers = ["benchmark: benchmarks"]\n'
            f"# {revision} configuration\n"
        )
        git("add", ".")
        git("commit", "-qm", revision)
        commits[revision] = git("rev-parse", "HEAD")

    output = tmp_path / "output"

    def invoke(*extra, base=True, mode="full"):
        arguments = [
            "run_benchmarks.py",
            "--head",
            commits["head"],
            "--python",
            sys.executable,
            "--output",
            str(output),
            "--mode",
            mode,
            "--seed",
            "reproducible",
        ]
        if base:
            arguments += ["--base", commits["base"]]
        monkeypatch.setattr(sys, "argv", [*arguments, *extra])
        return run_benchmarks.main()

    def restored():
        assert git("rev-parse", "HEAD") == commits["head"]
        assert git("status", "--porcelain") == ""

    return SimpleNamespace(
        module=run_benchmarks,
        repo=repository,
        output=output,
        git=git,
        base=commits["base"],
        head=commits["head"],
        invoke=invoke,
        restored=restored,
        read=lambda name: json.loads((output / name).read_text()),
    )


def test_real_pytest_runs_both_sources_with_head_harness(runner):
    assert runner.invoke() == 0
    for revision, filename in (
        ("base", "baseline_results.json"),
        ("head", "benchmark_results.json"),
    ):
        result = runner.read(filename)
        assert result["commit_info"]["id"] == getattr(runner, revision)
        assert result["fixture"]["revision"] == revision
        assert result["fixture"]["python"] == sys.executable
        assert result["benchmarks"][0]["fullname"] == "tests/test_state_benchmarks.py::test_source"
        assert result["benchmarks"][0]["stats"]["rounds"] == 2
    runs = runner.read("execution.json")["runs"]
    assert {run["revision"] for run in runs} == {"base", "head"}
    assert all(run["duration_seconds"] >= 0 for run in runs)
    runner.restored()


@pytest.mark.parametrize("revision, expected", [("base", 0), ("head", 2)])
def test_failed_revision_retains_logs_and_restores_head(runner, monkeypatch, revision, expected):
    monkeypatch.setenv("FAIL_REVISION", revision)
    assert runner.invoke() == expected
    runs = runner.read("execution.json")["runs"]
    failed = next(run for run in runs if run["revision"] == revision)
    assert failed["returncode"] == 1
    assert (runner.output / failed["result"]).exists()
    assert (
        "AssertionError" in (runner.output / failed["result"]).with_name("pytest.log").read_text()
    )
    filename = "baseline_results.json" if revision == "base" else "benchmark_results.json"
    assert not (runner.output / filename).exists()
    if revision == "base":
        assert runner.read("benchmark_results.json")["commit_info"]["id"] == runner.head
    runner.restored()


@pytest.mark.parametrize("mode", ["full", "focused"])
def test_wrong_source_measurement_is_rejected(runner, monkeypatch, mode):
    monkeypatch.setenv("WRONG_SHA_REVISION", "head")
    assert runner.invoke(base=mode == "focused", mode=mode) == 2
    assert "wrong source commit" in runner.read("execution.json")["error"]
    assert "regression" not in runner.read("report.json")
    runner.restored()


@pytest.mark.parametrize("mode", ["full", "focused"])
def test_missing_result_does_not_reuse_stale_json(runner, monkeypatch, mode):
    runner.output.mkdir()
    result = runner.output / "benchmark_results.json"
    result.write_text('{"stale": true}')
    real_run = subprocess.run

    def remove_result(command, **kwargs):
        completed = real_run(command, **kwargs)
        if command[1:3] == ["-m", "pytest"]:
            Path(command[command.index("--benchmark-json") + 1]).unlink()
        return completed

    monkeypatch.setattr(runner.module.subprocess, "run", remove_result)
    assert runner.invoke(base=mode == "focused", mode=mode) == 2
    assert not result.exists()
    assert "regression" not in runner.read("report.json")
    runner.restored()


@pytest.mark.parametrize("filename", ["source.txt", "obsolete.txt"])
def test_changed_or_untracked_work_is_preserved(runner, filename):
    path = runner.repo / filename
    path.write_text("unrelated work")
    assert runner.invoke() == 2
    assert path.read_text() == "unrelated work"
    assert runner.git("rev-parse", "HEAD") == runner.head
    assert runner.read("execution.json")["runs"] == []


def test_wrong_initial_revision_is_not_changed(runner):
    runner.git("checkout", "-q", "--detach", runner.base)
    assert runner.invoke() == 2
    assert runner.git("rev-parse", "HEAD") == runner.base


@pytest.mark.parametrize("option", ["--blocks", "--rounds"])
def test_nonpositive_measurement_counts_are_rejected(runner, option):
    with pytest.raises(SystemExit, match="2"):
        runner.invoke(option, "0", mode="focused")
    runner.restored()


@pytest.mark.parametrize("blocks", [2, 10])
def test_focused_blocks_exclude_warmups_and_remain_advisory(runner, monkeypatch, blocks):
    real_run = subprocess.run
    commands, caches = [], []

    def measure(command, **kwargs):
        if command[1:3] != ["-m", "pytest"]:
            return real_run(command, **kwargs)
        commands.append(command)
        caches.append(kwargs["env"]["PYTHONPYCACHEPREFIX"])
        revision = (runner.repo / "source.txt").read_text()
        value = 1.1 if revision == "head" else 1.0
        result = {
            "commit_info": {"id": getattr(runner, revision)},
            "benchmarks": [{"fullname": "test", "stats": {"median": value}}],
        }
        Path(command[command.index("--benchmark-json") + 1]).write_text(json.dumps(result))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(runner.module.subprocess, "run", measure)
    assert runner.invoke("--rounds", "25", "--blocks", str(blocks), mode="focused") == 0
    runs = runner.read("execution.json")["runs"]
    assert len(runs) == len(set(caches)) == 2 + blocks * 4
    assert all(run["warmup"] for run in runs[:2])
    assert not any(run["warmup"] for run in runs[2:])
    for offset in range(2, len(runs), 4):
        order = [run["revision"] for run in runs[offset : offset + 4]]
        assert order in (["base", "head", "head", "base"], ["head", "base", "base", "head"])
    assert all(command[0] == sys.executable for command in commands)
    assert all(
        command[command.index("--benchmark-min-rounds") + 1] == "25" for command in commands
    )
    assert runner.read("report.json")["block_count"] == blocks
    assert runner.read("report.json")["regression"] == (blocks == 10)
    assert "advisory" in (runner.output / "report.md").read_text().lower()
    runner.restored()
