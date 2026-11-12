# How to contribute

<!--
Keep this file in sync with the developer guide in docs/dev/:
- "Setup" with docs/dev/setup.md, and
- "Tests and formatting" with docs/dev/workflows.md, and
- "Benchmarks" with docs/dev/benchmarks.md
-->

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
The development dependencies bootstrap conda with a compatible solver from
`conda-canary/label/dev`, then replace it with this checkout for tests and benchmarks.

## Tests and formatting

Run tests with Python 3.13:

```shell
pixi run --locked -e test-py313 test
```

Choose another Python version with an environment such as `test-py311` or
`test-py314`. Run the pre-commit formatters and checks with:

```shell
pixi run --locked lint
```

Include a [news entry](./news/TEMPLATE) for changes that need release notes.

## Benchmarks

Solver and index performance is tracked with
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) and published to
[Bencher](https://bencher.dev/perf/conda-rattler-solver).

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

### Solver overhead workloads

The [solver overhead benchmarks](./tests/test_solver_overhead_benchmarks.py) use
synthetic local channels. Run them with:

```shell
pixi run --locked -e test-py313 benchmark -k 'pinned_request or empty_package_cache'
```

Use `-k pinned_request` or `-k empty_package_cache` to select one workload:

- The pinned-request benchmark has 10 package names with 200 candidate builds
  each. Pins exclude the newest version. It times `solve_final_state()`, including
  metadata loading and pin validation. Channel and prefix creation, plus solver
  construction, happen before timing starts.
- The empty-cache benchmark requests 100 or 563 packages. It times index
  construction and a Rattler solve, including package-cache source callbacks.
  Channel creation and request-spec construction happen before timing starts.

Both workloads clear conda's in-memory metadata and package-cache objects before
each round, outside the timed operation. Filesystem caches are left intact.

### Add benchmarks

Add tests marked with `@pytest.mark.benchmark` and time the operation with the
`benchmark` fixture. See the [index benchmarks](./tests/test_index.py) and
[solver benchmarks](./tests/test_solver.py) for examples.

Keep fixture setup outside the timed callable unless it is part of the operation
you intend to measure. Use fixed test data and stable test names and parameter IDs
so Bencher can track the same workload across commits. For cache-sensitive
benchmarks, define whether each case measures a cold or warm cache.

The existing tests cover index searches, installed-package solver handling, and
end-to-end solve comparisons between rattler and libmamba.

### Input-state reuse

`tests/test_state_benchmarks.py` measures first collection, including input-state
construction, and repeated collection with a rebuilt output state at 100, 563
and 1,000 installed packages. It also measures a complete 563-package update
fallback that needs three actual Rattler attempts. Prefix and channel fixtures
are created outside the timed operations. Select these cases with `-k state_`.
See [Input-state reuse](./docs/dev/benchmarks.md#input-state-reuse) for timing and
memory interpretation.

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
