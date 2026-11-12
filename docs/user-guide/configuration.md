# Configuration

## Basic options

conda-rattler-solver is a _solver plugin_ and is configured with the same
settings as other solvers in the conda ecosystem. This is usually done
via the `conda config` subcommand, the `.condarc` file, or `CONDA_*`
environment variables. Read the
[conda configuration docs](https://docs.conda.io/projects/conda/en/stable/configuration.html)
for the full list. The settings listed below are the ones that matter most
for the solver.

### `solver`

Selects the solver plugin. Starting with conda 26.10, conda-rattler-solver is
the default, so you only need this setting on older conda releases or to switch
between solvers:

```console
$ conda config --set solver rattler
```

The `--solver` command line flag and the `CONDA_SOLVER` environment variable
override this setting for a single command.

### `channel_priority`

Controls how the solver chooses between packages that are available from more
than one channel. conda's `strict`, `flexible`, and `disabled` modes map onto
rattler's own channel priority modes. `flexible` is the default. Note that
`disabled` does not sort candidates exactly as `classic` does. See
[](known-limitations) for details.

```console
$ conda config --set channel_priority strict
```

### `pinned_packages`

Specs listed in `pinned_packages` or in the target environment's
`conda-meta/pinned` file constrain the solve. Like `libmamba`, rattler
rejects command-line requests that conflict with configured pins instead
of overriding the pins as `classic` does. Edit or remove the pin before
requesting a conflicting version. Direct pin conflicts can raise
`SpecsConfigurationConflictError`.

If a package is already installed, a pin containing only its name locks
it to its installed version and build.

### `add_pip_as_python_dependency`

When enabled, `pip` is added as a dependency of `python` so that every
environment with Python also gets `pip`. conda-rattler-solver honours this
setting for regular, sharded, and offline repodata, so it behaves the same
as the other solvers.

````{admonition} Upcoming default change
:class: note

The default is `true` today and will change to `false` in conda 27.9, with a
deprecation warning from conda 27.3 onwards (see
[conda/conda#16404](https://github.com/conda/conda/issues/16404)). If you rely
on `pip` being installed with Python, set the option explicitly:

```console
$ conda config --set add_pip_as_python_dependency true
```
````

### `repodata_use_shards`

The conda-rattler-solver can read [sharded repodata](https://conda.org/learn/ceps/cep-0016),
which lets it fetch only the metadata for the packages involved in a solve
rather than a channel's full `repodata.json`. This is controlled by conda's
`repodata_use_shards` setting, which is enabled by default. To fall back to
full repodata downloads:

```console
$ conda config --set repodata_use_shards false
```

or pass `--no-repodata-use-shards` to a single command. Channels that do not
publish sharded repodata are fetched the usual way, regardless of the value
of this setting.
