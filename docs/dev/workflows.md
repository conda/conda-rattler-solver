# Typical development workflows

```{note}
Check out ["How to set up your development environment"](setup.md) if you
haven't yet!
```

## Testing

The solver is a critical part of `conda` as a tool. In addition to the unit and
integration tests for `conda_rattler_solver`, our CI also runs the full
`conda/conda` test suite and the shared
[pytest-conda-solvers](https://github.com/conda-incubator/pytest-conda-solvers)
suite against the rattler backend.

### conda-rattler-solver tests

% Keep this section and "Linting" in sync with the "Tests and formatting"
% section of CONTRIBUTING.md.

Run the tests with Python 3.13:

```shell
pixi run --locked -e test-py313 test
```

Choose another Python version with an environment such as `test-py311` or
`test-py314`. Arguments after the task name are passed through to `pytest`, so
you can select tests as usual:

```shell
pixi run --locked -e test-py313 test -k channel_priority
```

### Linting

Run the pre-commit formatters and checks with:

```shell
pixi run --locked lint
```

### Upstream `conda` tests

The [Tests workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/tests.yml)
also runs conda's own test suite with `CONDA_TEST_SOLVERS=rattler`. To run
it locally, use a clone of `conda/conda` next to this repository. Follow
[conda's development environment guide](https://docs.conda.io/projects/conda/en/stable/dev-guide/development-environment.html)
and activate that environment, then install conda-rattler-solver in editable
mode with its dependencies using [Manual setup](setup.md#manual-setup).
The Pixi test environments above do not include all of conda's test
dependencies.

From the conda-rattler-solver checkout, run:

```shell
cd ../conda
CONDA_TEST_SOLVERS=rattler python -m pytest
```

### The pytest-conda-solvers suite

[pytest-conda-solvers](https://github.com/conda-incubator/pytest-conda-solvers)
is a shared YAML test suite that runs the same solver scenarios against
`classic`, `libmamba`, and `rattler`. The
[Pytest Conda Solvers workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/pytest-conda-solvers.yml)
runs it on every push and pull request. To run it locally, install
pytest-conda-solvers into an environment that has conda-rattler-solver, then
select the solver with `--conda-solver`:

```shell
git clone https://github.com/conda-incubator/pytest-conda-solvers.git
cd pytest-conda-solvers
python -m pip install -e .
python -m pytest --conda-solver=rattler -vv
```

Known limitations of the rattler backend are carried in the suite as strict
`xfail_solvers: rattler` marks, so an unexpected pass is reported as a failure
and tells you that a mark can be removed. See [](../user-guide/known-limitations)
for the list. Please also remember to update that page when you remove a mark.

## Adding a news entry

Include a [news entry](https://github.com/conda/conda-rattler-solver/blob/main/news/TEMPLATE)
for changes that need release notes. Copy `news/TEMPLATE` to
`news/<PR number>-<short-description>.md` and fill in the relevant section.
The release process collects these files into the [changelog](changelog).

## Building the documentation

The documentation you are reading is built with Sphinx from the `docs/`
directory. Build it with:

```shell
pixi run --locked -e docs docs
```

Then serve the result locally with:

```shell
pixi run --locked -e docs serve
```

and open <http://localhost:8000> in your browser. The
[Docs workflow](https://github.com/conda/conda-rattler-solver/actions/workflows/docs.yml)
builds the site on every pull request that touches it and publishes it to
GitHub Pages on pushes to `main`.
