# User Guide

The `conda-rattler-solver` plugin lets you use the solver that powers
[`pixi`](https://pixi.sh), directly in `conda`. The solver is called
[`resolvo`](https://github.com/prefix-dev/resolvo), and it reaches `conda`
through the Rust-based [`rattler`](https://github.com/conda/rattler) library
and its Python bindings, `py-rattler`.

Environments solve meaningfully faster with `rattler`, especially large or
complex ones, and your existing environments and workflows keep working.

<!-- TODO: remove this once we make it the default? Keep in sync with README.md -->
```{admonition} Project status
:class: warning

conda-rattler-solver is in beta. Opt in to test it and send us your
feedback, but it is not yet recommended for production use.
```

## How to install

% Once conda-rattler-solver ships as the default solver (planned for conda 26.10,
% see https://github.com/conda/conda/issues/16853 and
% https://github.com/conda/conda-rattler-solver/issues/173), replace the paragraph
% below with the conda-libmamba-solver wording (fill in the conda version):
%
% If you have a recent `conda` (26.10 or later), you don't have to do anything.
% conda-rattler-solver is already preconfigured as default. For older versions of
% `conda`, we simply recommend updating `conda` to a more recent version:

conda-rattler-solver requires `conda` 26.7 or later. If you have an older
`conda`, we simply recommend updating `conda` to a more recent version first:

```console
$ conda update -n base conda
```

Then install the package in your `base` environment:

```console
$ conda install -n base conda-rattler-solver
```

Development builds are published to the `conda-canary` channel under the `dev`
label:

```console
$ conda install -n base conda-canary/label/dev::conda-rattler-solver
```

## Usage

% Once conda-rattler-solver ships as the default solver (planned for conda 26.10,
% see https://github.com/conda/conda/issues/16853 and
% https://github.com/conda/conda-rattler-solver/issues/173), add this above the
% subsections below (fill in the conda version) and move the "Set it as the
% default" subsection into a "Usage with conda 26.9 and below" admonition, as
% the conda-libmamba-solver docs do:
%
% From `conda` 26.10, conda-rattler-solver is the default solver. You don't have
% to do anything else. It will just work.

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

To use rattler for every solve, add `solver: rattler` to your `.condarc` file,
either manually or with this command:

```console
$ conda config --set solver rattler
```

## Switching back

If you ever need another solver temporarily, use the `--solver` flag:

```console
$ conda install numpy --solver=libmamba
$ conda install numpy --solver=classic
```

To revert the default configuration, remove the `solver` key:

```console
$ conda config --remove-key solver
```

`conda` then falls back to its own default, which is `libmamba`. You can also
make a different choice explicit with `conda config --set solver libmamba`.

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
