# User Guide

The `conda-rattler-solver` plugin lets you use the solver that powers
[`pixi`](https://pixi.sh), directly in `conda`. The solver is called
[`resolvo`](https://github.com/prefix-dev/resolvo), and it reaches `conda`
through the Rust-based [`rattler`](https://github.com/conda/rattler) library
and its Python bindings, `py-rattler`.

Environments solve meaningfully faster with `rattler`, especially large or
complex ones, and your existing environments and workflows keep working.

<!-- Keep in sync with README.md -->
```{admonition} Project status
:class: note

conda-rattler-solver is conda's default solver starting with conda 26.10.
```

## How to install

If you have conda 26.10 or later, conda-rattler-solver is the default solver,
so no installation or configuration is needed.

conda-rattler-solver has shipped with conda since 26.5. To use it on conda 26.5
to 26.9, select it as your solver:

```console
$ conda config --set solver rattler
```

If you have an older `conda`, we simply recommend updating `conda` to a more
recent version first:

```console
$ conda self update --all
```

Development builds are published to the `conda-canary` channel under the `dev`
label:

```console
$ conda install -n base conda-canary/label/dev::conda-rattler-solver
```

## Usage

From `conda` 26.10, conda-rattler-solver is the default solver. You don't have
to do anything else.

### Try it on a single command

The `--solver` flag is available for `conda create`, `conda install`,
`conda remove`, and `conda update`, and lets you use the solver without
changing your configuration:

```console
$ conda install numpy --solver=rattler
```

The flag is also exposed as the `CONDA_SOLVER` environment variable, in case
you need that:

```console
$ CONDA_SOLVER=rattler conda install numpy
```

### Set it as the default

This is only needed on conda 26.9 and below. To use rattler for every solve, add
`solver: rattler` to your `.condarc` file, either manually or with this command:

```console
$ conda config --set solver rattler
```

## Switching back

If you ever need another solver temporarily, use the `--solver` flag:

```console
$ conda install numpy --solver=libmamba
```

To revert the default configuration, remove the `solver` key:

```console
$ conda config --remove-key solver
```

On conda 26.10 and later, `conda` then falls back to its own default, which is
`rattler`; older releases fall back to `libmamba`. You can also make a different
choice explicit with `conda config --set solver libmamba`.

```{tip}
If you are unsure what configuration is being used by conda, you can inspect
it with `conda config --show-sources`.
```

```{toctree}
:hidden:

configuration
known-limitations
faq
more-resources
```
