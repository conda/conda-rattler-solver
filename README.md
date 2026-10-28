# conda-rattler-solver

[![Benchmarks](https://github.com/conda/conda-rattler-solver/actions/workflows/benchmarks.yml/badge.svg?branch=main)](https://github.com/conda/conda-rattler-solver/actions/workflows/benchmarks.yml?query=branch%3Amain)
[![Bencher Performance Benchmarks](https://img.shields.io/badge/benchmarks-Bencher-blue)](https://bencher.dev/perf/conda-rattler-solver)

The fast, Rust-based solver for conda.

Documentation: https://conda.github.io/conda-rattler-solver/

## What is this exactly?

`conda-rattler-solver` brings the [`resolvo`](https://github.com/prefix-dev/resolvo) solver, as provided by [`rattler`](https://github.com/conda/rattler), to `conda`. Environments solve meaningfully faster than with the `classic` and `libmamba` solvers, especially large or complex ones, and your existing environments and workflows keep working. It is conda's default solver starting with conda 26.10.

### Project status

<!-- Keep in sync with docs/index.md Project status heading -->
Stable - Default solver in conda 26.10 and later. See the
[conda documentation](https://docs.conda.io/projects/conda/en/latest/new-features.html#faster-solves-conda-rattler-solver-is-now-condas-default-solver)
and the [user guide](https://conda.github.io/conda-rattler-solver/user-guide/) for details.

## Install instructions

Starting with conda 26.10, conda-rattler-solver is conda's default solver, so no
configuration is needed.

conda-rattler-solver has shipped with conda since 26.5. To use it on 26.5 to
26.9, select it as your solver:

```
conda config --set solver rattler
```

Check your configured solver at any time:

```
conda config --show solver
```

To switch back to conda-libmamba-solver:
```
conda config --set solver libmamba
```

To restore conda's default solver:
```
conda config --remove-key solver
```

To use rattler for a single command without changing your configuration, pass `--solver rattler`:

```
conda install --solver rattler <package>
```

## Contributing

See the [contributor guide](./CONTRIBUTING.md) for setup and tests, and its
[benchmarking section](./CONTRIBUTING.md#benchmarks) for local runs and performance results.

## Build status

| [![Build status](https://github.com/conda/conda-rattler-solver/actions/workflows/tests.yml/badge.svg)](https://github.com/conda/conda-rattler-solver/actions/workflows/tests.yml?query=branch%3Amain) | [![Anaconda-Server Badge](https://anaconda.org/conda-canary/conda-rattler-solver/badges/latest_release_date.svg)](https://anaconda.org/conda-canary/conda-rattler-solver) |
| --- | :-: |
| [`conda install defaults::conda-rattler-solver`](https://anaconda.org/anaconda/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/anaconda/conda-rattler-solver/badges/version.svg)](https://anaconda.org/anaconda/conda-rattler-solver) |
| [`conda install conda-forge::conda-rattler-solver`](https://anaconda.org/conda-forge/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/conda-forge/conda-rattler-solver/badges/version.svg)](https://anaconda.org/conda-forge/conda-rattler-solver) |
| [`conda install conda-canary/label/dev::conda-rattler-solver`](https://anaconda.org/conda-canary/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/conda-canary/conda-rattler-solver/badges/version.svg)](https://anaconda.org/conda-canary/conda-rattler-solver) |
