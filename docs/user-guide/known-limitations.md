# Known limitations and differences

conda-rattler-solver aims to be a drop-in replacement for the `classic` and
`libmamba` solvers, but it is still in beta and there are some areas where it
behaves differently. This page lists these known limitations and differences.

```{tip}
You can always use `--solver=classic` or `--solver=libmamba` to run a single
operation with another solver, even after setting `rattler` as the default.
```

## Features and `track_features`

The legacy `features` metadata, as used by old `mkl` and `nomkl` variant
packages, is not supported. This limitation is shared with `libmamba`. If you
depend on packages that select variants through `features`, use the `classic`
solver for those environments.

## Custom multichannels

A multichannel is a single channel name that conda expands to several real
channels, as configured through the `custom_multichannels` and
`default_channels` settings. conda-rattler-solver does not yet fully support
them, so the following do not work as expected:

* Specs that pin a package to a multichannel, such as `<multichannel>::<package>`.
* The `local` channel, which points at `conda-build`'s output directory.
* Custom `default_channels` entries, for example channels that carry an
  authentication token.

% TODO: update this after conda/conda-rattler-solver#182 is merged

## Channel priority

With `channel_priority: disabled`, `classic` prefers the higher-priority
channel when the same version is available from several channels.
conda-rattler-solver may pick a build from a lower-priority channel instead.
See
[conda/rattler#2823](https://github.com/conda/rattler/issues/2823). The
default, `flexible`, and `strict` are not affected.

% TODO: remove the paragraph below when PR #181 (additional_packages, issue
% #174) is merged. It drops the xfail on the test for this case.

With `channel_priority: strict`, if an installed package came from a channel
that is no longer in your configuration and one of your active channels also
provides it, conda-rattler-solver replaces it with the active channel's build,
even when that means a downgrade. `classic` keeps the installed package. If
you need to keep it, add the original channel back or pin the package.

## Error messages

For unsatisfiable dependency conflicts, conda-rattler-solver reports
`RattlerUnsatisfiableError`. Its diagnostic walks through the packages
that were tried and explains which requirements could not be satisfied.

A request for an unavailable package can raise `PackagesNotFoundError`.
A direct conflict between requested specs and configured pins can raise
`SpecsConfigurationConflictError`. See
[`pinned_packages`](configuration.md#pinned_packages) for pinning behavior.

## Solutions that differ from `classic`

These are not bugs, but they can be surprising if you are used to the
`classic` solver:

* When an existing environment is re-solved with relaxed constraints,
  conda-rattler-solver may keep installed packages that `classic` would remove,
  as long as they are still compatible with the solution.
* conda-rattler-solver tries to minimise changes to your environment, but it
  does not implement `classic`'s multi-step retry logic with
  `--freeze-installed`. If a solve fails, it retries with progressively looser
  constraints on the conflicting packages. During an update this can downgrade
  a conflicting package if that is the only way to find a solution, which is
  what `libmamba` does too.

## Reporting a new difference

If you find a case where conda-rattler-solver and `classic` or `libmamba`
disagree and it is not listed here, please
[open an issue](https://github.com/conda/conda-rattler-solver/issues/new/choose)
with the command you ran, your channel configuration, and the output of
`conda info`.
