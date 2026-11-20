# conda-rattler-solver

`conda-rattler-solver` brings the Rust-based
[`resolvo`](https://github.com/prefix-dev/resolvo) solver to `conda`
through [`rattler`](https://github.com/conda/rattler).

<!-- Keep in sync with README.md -->
```{admonition} Project status
:class: note

conda-rattler-solver is conda's default solver starting with conda 26.10.
```

## Learn

::::{grid} 2

:::{grid-item-card} Getting started
:link: user-guide/index
:link-type: doc
New to conda-rattler-solver? Start here to learn how to install and use it
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
