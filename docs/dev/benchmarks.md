# Benchmarks

% Keep this page in sync with the "Benchmarks" section of CONTRIBUTING.md.

Solver and index performance is tracked with
[pytest-benchmark](https://pytest-benchmark.readthedocs.io/) and published to
[Bencher](https://bencher.dev/perf/conda-rattler-solver).

## Run locally

Run the existing solver and index benchmarks with the same Python environment
as CI:

```shell
pixi run --locked -e test-py313 benchmark
```

Export the measurements as pytest-benchmark JSON:

```shell
pixi run --locked -e test-py313 benchmark --benchmark-json benchmark_results.json
```

The JSON file is ignored by Git. Local runs do not upload results to Bencher.
To select a smaller group, append a pytest filter such as `-k query_search`.
Compare local timings on the same machine with the same environment and cache
state.

## Solver overhead workloads

The [solver overhead benchmarks](https://github.com/conda/conda-rattler-solver/blob/main/tests/test_solver_overhead_benchmarks.py)
use synthetic local channels. Run them with:

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

## Add benchmarks

Add tests marked with `@pytest.mark.benchmark` and time the operation with the
`benchmark` fixture. See the
[index benchmarks](https://github.com/conda/conda-rattler-solver/blob/main/tests/test_index.py)
and [solver benchmarks](https://github.com/conda/conda-rattler-solver/blob/main/tests/test_solver.py)
for examples.

Keep fixture setup outside the timed callable unless it is part of the
operation you intend to measure. Use fixed test data and stable test names and
parameter IDs so Bencher can track the same workload across commits. For
cache-sensitive benchmarks, define whether each case measures a cold or warm
cache.

The existing tests cover index searches, installed-package solver handling, and
end-to-end solve comparisons between rattler and libmamba.

## Results and regression alerts

The [Benchmarks workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/benchmarks.yml)
runs on pushes to `main` and pull requests targeting `main`, and can also be run
manually. It uses Ubuntu 24.04, Python 3.13 and the Pixi lockfile. Both revisions
share the same checked-out conda test data. Its `benchmark-results-v3` artifact
contains the JSON measurements, workflow event, dependency list, and runner
diagnostics, retained for seven days.

The [Track Benchmarks workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/bencher.yml)
uses the shared Bencher reporting action in
[`conda/actions`](https://github.com/conda/actions) to upload available results to the
[Bencher project](https://bencher.dev/perf/conda-rattler-solver).
Select `main` for historical results. Manual runs keep downloadable artifacts
but do not upload to Bencher because the shared reporter accepts push and
pull-request events only.

PR measurements use the exact base and head commits on the same runner with
`PYTHONHASHSEED=0`, the head revision's resolved dependencies, benchmark tests,
and fixtures. Running both revisions roughly doubles the benchmark execution time.
The base runs first, so the head can benefit from filesystem, package and network
caches warmed by the base. This comparison screens for larger regressions. It
does not establish that a small timing difference is repeatable. Both results
must contain the same benchmark names. If the base revision
cannot run the complete head benchmark suite, the head results remain available
and the `Benchmark comparison` check is neutral.

The reporting workflow creates a separate baseline for each PR workflow run and
attempt. Select `pr-<number>` for its comparison. This baseline never replaces the
`main` history. PR alerts use Bencher's percentage test with one baseline
measurement and an initial 25% slowdown tolerance, following the
[relative benchmarking example](https://bencher.dev/docs/how-to/track-benchmarks/#relative-continuous-benchmarking).
This is a starting tolerance for noisy shared runners, to adjust using observed
variation. A green result does not rule out smaller regressions.

Non-PR runs preserve the branch's history and use a t-test at `0.99`, with at least
10 and at most 64 historical measurements. The `0.99` value is a statistical
prediction level, not a 1% slowdown allowance. A new benchmark or testbed may have
too little history to produce an alert. Missing comparison warnings remain visible.

Testbeds include the producer's Ubuntu version, architecture, Python major/minor
version, and CPU model. Ubuntu 24.04 measurements start separate histories from
Ubuntu 22.04. Runner image versions are recorded in `runner_metadata.json` and
`bencher noise` diagnostics in `noise.txt`, alongside the raw results. Noise
measurements are diagnostic only and do not change timings or alert thresholds.

The same CPU model can still have different contention, cache state, or frequency.
Dependencies can change between workflow runs even though each base/head pair
shares an environment. Inspect the measurements and runner diagnostics before
changing a threshold. Give benchmarks new names when their timed work or fixtures
change so historical comparisons do not combine different workloads.

The versioned artifact name prevents the older reporting workflow from treating
Ubuntu 24.04 measurements as Ubuntu 22.04 results while this change is in review.

## Input-state reuse

`tests/test_state_benchmarks.py` measures spec collection for 100, 563, and
1,000 installed packages. The `first` cases include input-state construction,
output-state construction, and spec collection. The `retry` cases populate the
input-derived values before timing, then rebuild the output state and collect
specs again. Record creation stays outside both timed operations.

The same module includes a complete 563-package update fallback. A pinned app
requires an older dependency build, forcing three Rattler attempts across the
normal and fallback loops. This case checks the resulting transaction as well
as the attempt count. Local channel and prefix creation are outside timing.

Run this group with `-k state_` or pass `tests/test_state_benchmarks.py` to the
benchmark task. Compare first collection, repeated collection, and complete
solves separately. A faster repeated collection does not imply the same
percentage improvement for the full solve. Use separate processes for Python
allocation measurements, since tracing affects timing, and distinguish retained
input-state data from allocation peaks and native Rattler memory.
