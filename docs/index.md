# conda-rattler-solver

% TODO: mention that conda-rattler-solver ships as the default solver as planned for conda 26.10.0. See
% https://github.com/conda/conda/issues/16853 and
% https://github.com/conda/conda-rattler-solver/issues/173)
% Something like https://github.com/agriyakhetarpal/conda-libmamba-solver/blob/dd6913aa05524ca95f0d7ff958f042b5334523b6/docs/index.md?plain=1#L3-L5
% "and is now the default solver"?

Welcome to the conda-rattler-solver documentation! The conda-rattler-solver brings
the [`resolvo`](https://github.com/prefix-dev/resolvo) solver used by
[`pixi`](https://pixi.sh), as provided by [`rattler`](https://github.com/conda/rattler),
to `conda` as a solver plugin. On this site, you will find information about how
to install, configure, and use this solver.

<!-- TODO: remove this once we make it the default? Keep in sync with README.md -->
```{admonition} Project status
:class: warning

conda-rattler-solver is in beta. Opt in to test it and send us your
feedback, but it is not yet recommended for production use.
```

## Learn

::::{grid} 2

:::{grid-item-card} Getting started
:link: user-guide/index
:link-type: doc
New to conda-rattler-solver? Start here to learn how to install and enable it
:::

:::{grid-item-card} Configuration
:link: user-guide/configuration
:link-type: doc
Learn about the configuration options that affect the solver
:::

:::{grid-item-card} Known limitations
:link: user-guide/known-limitations
:link-type: doc
Where rattler behaves differently from the classic and libmamba solvers
:::

:::{grid-item-card} FAQ
:link: user-guide/faq
:link-type: doc
Answers to frequently asked questions
:::

::::

## Development

::::{grid} 2

:::{grid-item-card} Development environment
:link: dev/setup
:link-type: doc
Learn how to set up your development environment
:::

:::{grid-item-card} Changelog
:link: dev/changelog
:link-type: doc
Recent changes and updates to the project
:::

::::

```{seealso}
Found a bug? [File an issue here](https://github.com/conda/conda-rattler-solver/issues/new/choose)
```

```{toctree}
:hidden:

user-guide/index
dev/index
```
