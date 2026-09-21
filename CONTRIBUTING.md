# How to contribute

## Setup

Install [Pixi](https://pixi.sh/latest/installation/) and Git. Clone this repository
alongside conda, whose test data is used by the test and benchmark tasks:

```shell
git clone https://github.com/conda/conda.git
git clone https://github.com/conda/conda-rattler-solver.git
cd conda-rattler-solver
```

The tasks expect conda's test data at `../conda/tests/data`. Pixi installs the
locked dependencies and an editable copy of this repository when you run them.

## Tests and formatting

Run tests with Python 3.13:

```shell
pixi run --locked -e test-py313 test
```

Choose another Python version with an environment such as `test-py310` or
`test-py314`. Run the pre-commit formatters and checks with:

```shell
pixi run --locked lint
```

Include a [news entry](./news/TEMPLATE) for changes that need release notes.

## Benchmarks

### Run locally

Run the existing solver and index benchmarks with the same Python environment as CI:

```shell
pixi run --locked -e test-py313 benchmark
```

Export the measurements as pytest-benchmark JSON:

```shell
pixi run --locked -e test-py313 benchmark --benchmark-json benchmark_results.json
```

The JSON file is ignored by Git. Local runs do not upload results to Bencher.
To select a smaller group, append a pytest filter such as `-k query_search`.
Compare local timings on the same machine with the same environment and cache state.

### Add benchmarks

Add tests marked with `@pytest.mark.benchmark` and time the operation with the
`benchmark` fixture. See [index benchmarks](./tests/test_index.py) and
[solver benchmarks](./tests/test_solver.py) for examples.

Keep fixture setup outside the timed callable unless it is part of the operation
you intend to measure. Use fixed test data and stable test names and parameter IDs
so Bencher can track the same workload across commits. For cache-sensitive
benchmarks, define whether each case measures a cold or warm cache.

The existing tests cover index searches and installed-package solver handling.
Representative end-to-end rattler/libmamba comparisons are tracked in
[#118](https://github.com/conda/conda-rattler-solver/issues/118).

### Results and regression alerts

The [Benchmarks workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/benchmarks.yml)
runs on pushes to `main` and pull requests targeting `main`, and can also be run
manually. It uses Ubuntu 22.04, Python 3.13 and the Pixi lockfile. Its
`benchmark-results` artifact contains the JSON measurements and is retained for seven days.

The [Track Benchmarks workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/bencher.yml)
uploads successful runs to the
[Bencher project](https://bencher.dev/perf/conda-rattler-solver).
Select `main` for the baseline or `pr-<number>` for a pull request.
Manual runs are uploaded only when run from `main`.

PR reports compare against the base branch's results. The latency threshold uses
a t-test with an upper threshold of `0.99` and at most 64 historical samples.
A first baseline run records measurements before comparisons can begin.
Detected regressions fail the reporting workflow and generate PR feedback.
Inspect the affected benchmark and its history before changing a threshold.
