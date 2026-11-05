# Copyright (C) 2026 conda
# SPDX-License-Identifier: BSD-3-Clause
"""Run installed dependencies against Git revisions in a disposable CI checkout."""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


def git(*arguments):
    return subprocess.check_output(["git", *arguments], text=True, stderr=subprocess.PIPE).strip()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def publish_report(output, result, markdown):
    write_json(output / "report.json", result)
    (output / "report.md").write_text(markdown, encoding="utf-8")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(markdown)


def validate(args, output):
    for revision in (args.base, args.head):
        if revision is not None:
            if not re.fullmatch(r"[a-f0-9]{40}", revision):
                raise ValueError("Revision arguments must be full lowercase commit SHAs")
            if git("rev-parse", "--verify", f"{revision}^{{commit}}") != revision:
                raise ValueError("Revision does not identify a commit")
    if args.mode == "focused" and not args.base:
        raise ValueError("Focused comparisons require --base")
    if git("rev-parse", "HEAD") != args.head:
        raise ValueError("The initial checkout must be at --head")
    if git("status", "--porcelain"):
        raise ValueError("The initial checkout must have no changed or untracked files")
    repository = Path(git("rev-parse", "--show-toplevel")).resolve()
    if Path.cwd().resolve() != repository:
        raise ValueError("Run from the repository root")
    if output.is_relative_to(repository) or Path(__file__).resolve().is_relative_to(repository):
        raise ValueError("Copy this runner and place its output outside the source checkout")
    if not args.python.is_file() or not os.access(args.python, os.X_OK):
        raise ValueError("--python must identify an executable in the installed environment")


def run_revision(args, output, execution, revision, *, warmup=False, block=None):
    sha = args.base if revision == "base" else args.head
    git("checkout", "--force", "--detach", sha)
    git("restore", "--source", args.head, "--worktree", "--", "tests", "pyproject.toml")
    number = len(execution["runs"])
    (output / "runs").mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=f"{number:03d}-{revision}-", dir=output / "runs"))
    raw = directory / "results.json"
    result_path = (
        output / ("baseline_results.json" if revision == "base" else "benchmark_results.json")
        if args.mode == "full"
        else raw
    )
    result_path.unlink(missing_ok=True)
    environment = dict(os.environ)
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONPYCACHEPREFIX=str(directory / "pycache"),
        PATH=str(args.python.parent) + os.pathsep + environment.get("PATH", ""),
    )
    command = [str(args.python), "-m", "pytest"]
    if args.mode == "focused":
        command.append("tests/test_state_benchmarks.py")
    command += [
        "-m",
        "benchmark",
        "--benchmark-only",
        "--benchmark-json",
        str(result_path),
        "--basetemp",
        str(directory / "pytest"),
    ]
    if args.rounds is not None:
        command += ["--benchmark-min-rounds", str(args.rounds)]
    record = {
        "revision": revision,
        "sha": sha,
        "warmup": warmup,
        "block": block,
        "result": str(raw.relative_to(output)),
        "returncode": None,
        "start_utc": datetime.now(timezone.utc).isoformat(),
        "start_monotonic": time.monotonic(),
    }
    execution["runs"].append(record)
    print(f"Starting process {number}: {revision} {sha[:12]}, warmup={warmup}", flush=True)
    log_path = directory / "pytest.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            record["returncode"] = subprocess.run(
                command, env=environment, stdout=log, stderr=subprocess.STDOUT
            ).returncode
        if args.mode == "full" and result_path.exists():
            shutil.copyfile(result_path, raw)
        if record["returncode"]:
            raise ValueError(f"pytest exited with status {record['returncode']}")
        data = json.loads(result_path.read_text(encoding="utf-8"))
        if data["commit_info"]["id"] != sha:
            raise ValueError("Benchmark JSON identifies the wrong source commit")
        if not isinstance(data["benchmarks"], list) or not data["benchmarks"]:
            raise ValueError("Benchmark JSON contains no measurements")
        return {**data, "revision": revision}
    except (OSError, ValueError, KeyError, TypeError) as error:
        record["error"] = str(error)
        print(f"Process {number} failed: {error}", flush=True)
        if log_path.exists():
            with log_path.open(encoding="utf-8", errors="replace") as log:
                print("".join(deque(log, maxlen=80)), end="", flush=True)
        if args.mode == "full":
            result_path.unlink(missing_ok=True)
        raise ValueError(f"{revision} process {number} failed: {error}") from error
    finally:
        record["end_monotonic"] = time.monotonic()
        record["end_utc"] = datetime.now(timezone.utc).isoformat()
        record["duration_seconds"] = record["end_monotonic"] - record["start_monotonic"]
        print(
            f"Finished process {number}: pytest={record['returncode']}, "
            f"{record['duration_seconds']:.1f}s",
            flush=True,
        )
        write_json(output / "execution.json", execution)


def run(args, output, execution):
    randomizer = random.Random(args.seed)
    order = ["base", "head"] if args.base else ["head"]
    randomizer.shuffle(order)
    if args.mode == "full":
        for revision in order:
            try:
                run_revision(args, output, execution, revision)
            except ValueError:
                if revision == "head":
                    raise
        return 0

    from benchmark_statistics import compare_blocks, render_report

    for revision in order:
        run_revision(args, output, execution, revision, warmup=True)
    blocks = []
    for number in range(args.blocks):
        order = randomizer.choice(
            (("base", "head", "head", "base"), ("head", "base", "base", "head"))
        )
        blocks.append(
            [run_revision(args, output, execution, revision, block=number) for revision in order]
        )
    report = compare_blocks(blocks)
    publish_report(output, report, render_report(report))
    return 0


def positive_int(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Measurement counts must be positive")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base")
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--python", required=True, type=lambda value: Path(value).expanduser().absolute()
    )
    parser.add_argument(
        "--output", required=True, type=lambda value: Path(value).expanduser().resolve()
    )
    parser.add_argument("--mode", choices=("full", "focused"), required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--blocks", type=positive_int, default=10)
    parser.add_argument("--rounds", type=positive_int)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    execution = {
        "mode": args.mode,
        "seed": args.seed,
        "base_sha": args.base,
        "head_sha": args.head,
        "blocks": args.blocks,
        "rounds": args.rounds,
        "runs": [],
    }
    validated = False
    status = 2
    try:
        validate(args, output)
        validated = True
        for name in (
            "baseline_results.json",
            "benchmark_results.json",
            "report.json",
            "report.md",
        ):
            (output / name).unlink(missing_ok=True)
        status = run(args, output, execution)
    except (OSError, ValueError, subprocess.SubprocessError, ImportError) as error:
        execution["error"] = str(error)
        publish_report(output, {"error": str(error)}, f"Benchmark execution failed: {error}\n")
    finally:
        if validated:
            try:
                git("checkout", "--force", "--detach", args.head)
            except subprocess.SubprocessError:
                execution["restore_error"] = "Could not restore the head checkout"
                status = 2
        execution["exit_code"] = status
        write_json(output / "execution.json", execution)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
