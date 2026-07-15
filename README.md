# conda-rattler-solver

The fast pixi solver, now in conda!

## What is this exactly?

If `conda-libmamba-solver` brought the `mamba` solver to `conda`, `conda-rattler-solver` tries to integrate the `pixi` solver (called `resolvo`, as provided in `rattler`) in `conda`.

Environments solve meaningfully faster with Rattler, especially large or complex ones, and your existing environments and workflows keep working.

### Project status

Beta - Opt in to test, not recommended for production. We want your feedback!

## Install instructions

Install the conda-rattler-solver package and switch your default solver to Rattler:

```
conda install --name base conda-rattler-solver
conda config --set solver rattler
```

To switch back at any time:
```
conda config --remove-key solver
```

You may also try this solver in isolated commands with no changes to your configuration by using the `--solver` flag:

## Contributing

Please refer to [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Build status

| [![Build status](https://github.com/conda/conda-rattler-solver/actions/workflows/tests.yml/badge.svg)](https://github.com/conda/conda-rattler-solver/actions/workflows/tests.yml?query=branch%3Amain) | [![Anaconda-Server Badge](https://anaconda.org/conda-canary/conda-rattler-solver/badges/latest_release_date.svg)](https://anaconda.org/conda-canary/conda-rattler-solver) |
| --- | :-: |
| [`conda install defaults::conda-rattler-solver`](https://anaconda.org/anaconda/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/anaconda/conda-rattler-solver/badges/version.svg)](https://anaconda.org/anaconda/conda-rattler-solver) |
| [`conda install conda-forge::conda-rattler-solver`](https://anaconda.org/conda-forge/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/conda-forge/conda-rattler-solver/badges/version.svg)](https://anaconda.org/conda-forge/conda-rattler-solver) |
| [`conda install conda-canary/label/dev::conda-rattler-solver`](https://anaconda.org/conda-canary/conda-rattler-solver) | [![Anaconda-Server Badge](https://anaconda.org/conda-canary/conda-rattler-solver/badges/version.svg)](https://anaconda.org/conda-canary/conda-rattler-solver) |
