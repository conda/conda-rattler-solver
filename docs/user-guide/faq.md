# Frequently Asked Questions

## What is the relationship between conda-rattler-solver, rattler, resolvo, and pixi?

[`resolvo`](https://github.com/prefix-dev/resolvo) is a dependency solver
written in Rust. [`rattler`](https://github.com/conda/rattler) is a Rust library
for working with the conda ecosystem, and it uses `resolvo` to solve conda
environments. [`pixi`](https://pixi.sh) is a package manager built on top of
`rattler`. conda-rattler-solver uses the Python bindings for `rattler`,
[`py-rattler`](https://pypi.org/project/py-rattler/), to make that same solver
available inside `conda` through its solver plugin interface.

## How do I check which solver is in use?

Run:

```console
$ conda config --show solver
```

If the output is `solver: rattler`, conda is using conda-rattler-solver. That
is the default from conda 26.10 onwards. To see where the setting comes from,
use `conda config --show-sources`.

## Do I need to configure conda to use the solver?

Starting with conda 26.10, no: conda-rattler-solver is the default solver. On
earlier releases, or if another solver was configured, make it the default with:

```console
$ conda config --set solver rattler
```

To undo this change and return to conda's default solver, run:

```console
$ conda config --remove-key solver
```

## I get an error when I pass `--solver=rattler`

If you see an error such as:

```
CondaValueError: Invalid choice for 'solver': rattler
```

the plugin is not installed in the environment that provides the `conda`
command, which is usually `base`. Install it there:

```console
$ conda install -n base conda-rattler-solver
```

## How do I uninstall it?

From conda 26.10, conda-rattler-solver is the default solver. To use a
different solver, select one:

```console
$ conda config --set solver libmamba
```

If you installed the plugin yourself on an earlier conda release, follow these
instructions:

```{warning}
Please make sure you __follow all steps below__ to uninstall the solver!
```

1. If you configured it as the default solver, revert it first:

    ```console
    $ conda config --remove-key solver
    ```

2. Then, remove the package from `base`:

    ```console
    $ conda remove -n base conda-rattler-solver
    ```

## Why does the solver pick a different solution than classic or libmamba?

All three solvers are correct, but they do not always agree when several
solutions satisfy the request. The underlying algorithms, and the order in
which they consider candidates, differ. Being more explicit about what you
want, for example, `conda install python=3.13 numpy` instead of
`conda install numpy`, narrows the solution space and usually gets you the
solution you expected. See [](known-limitations) for known differences.

## Where can I report a bug or ask for help?

Please [file an issue](https://github.com/conda/conda-rattler-solver/issues/new/choose)
in the conda-rattler-solver repository. For general questions, the
[conda Zulip](https://conda.zulipchat.com) is a good place to ask.
