# Changelog

[//]: # (current developments)

## 0.2.0 (2026-09-16)

### Enhancements

* Publish releases to PyPI with trusted publishing and artifact attestations. (#83 via #109)
* Suggest updating conda with `conda self` if conda self plugin is installed. (#96)
* Map conda's flexible channel priority to rattler's `Flexible` mode, instead of falling back to `Disabled`. Solves under the default priority setting now prefer higher-priority channels, matching classic and libmamba solver behaviour. (#125 via #152)

### Bug fixes

* Preserve the installed `conda` package and its Python requirements during
  `conda update python`, while honoring explicit Python pins and allowing
  `conda` to change when requested or needed to resolve a dependency conflict.
  (#100 via #137)
* Support searching channels with sharded repodata as part of `RattlerIndexHelper`. (#111)
* Fix `conda update --all` so Python is updated within the current major.minor series (e.g. 3.13.9 → 3.13.14), matching classic solver behavior. (#112 via #113)
* Fix MatchSpec conversion for package extras, using py-rattler's support
  for quoted extras. (#94 via #117 and #123)
* Honor `add_pip_as_python_dependency` across normal, sharded, and offline
  repodata sources. (#122)
* Prevent updates from selecting package versions older than those already installed. (#126)
* Retain installed packages that are unavailable from configured channels
  during updates. (#88 via #129)
* Load v3 package records from sharded channels via `iter_records_v3()`, fixing installs from v3-native channels. (#92 via #66)
* Fix `InvalidMatchSpec` errors being raised when parsing rattler solver diagnostics that reference requested extras. (#154)

### Deprecations

* Require Python 3.11 or newer for conda packages to match py-rattler's
  conda-forge builds. (#123)

### Docs

* Document installation and opt-in use of the beta solver. (#74)
* Document running and adding benchmarks, and link to Bencher results. (#144)
* Switch to using the new on-demand release process. (#80)

### Other

* Require `py-rattler >=0.26.0,<0.27.0a0`. (#123)
* Track solver and index benchmarks with Bencher. (#144)
* Require `conda >=26.7.0` for the shards `iter_records_v3()` API. (#66)
* Fix tests failing locally by using conda-pypi for editable installs. (#82)
* Enable infrastructure-managed Dependabot configuration via conda/infrastructure templates. (#84)
* Add solve-time benchmarks comparing rattler vs libmamba for small, medium, and large environments, including conflict and cold/warm cache cases. (#118)

### Contributors

* @agriyakhetarpal made their first contribution in https://github.com/conda/conda-rattler-solver/pull/152
* @danyeaw
* @dholth
* @jezdez
* @kenodegard made their first contribution in https://github.com/conda/conda-rattler-solver/pull/95
* @ForgottenProgramme made their first contribution in https://github.com/conda/conda-rattler-solver/pull/117
* @ryanskeith made their first contribution in https://github.com/conda/conda-rattler-solver/pull/137
* @soapy1
* @travishathaway made their first contribution in https://github.com/conda/conda-rattler-solver/pull/154
* @conda-bot
* @dependabot[bot] made their first contribution in https://github.com/conda/conda-rattler-solver/pull/86



## 0.1.1 (2026-06-11)

### Enhancements

* Bump `py-rattler` to `>=0.25.0,<0.26.0a0` to restore `ppc64le` support for the conda-forge build of conda. (#69)

### Bug fixes

* Raise the conda-build-specific exception when solver problems are inferred, so conda-build receives the expected error type instead of a generic conflict. (#65)

### Other

* Update the conda dependency to `conda >=26.5.0` and correct the 0.1.0 release date in the changelog. (#63, #64)

### Contributors

* @danyeaw
* @jsmolic made their first contribution in https://github.com/conda/conda-rattler-solver/pull/65
* @jezdez
* @conda-bot made their first contribution in https://github.com/conda/conda-rattler-solver/pull/71



## 0.1.0 (2026-05-16)

* Bump conda dependency to 26.5.0 by @soapy1 #61
* Enable conditional dependencies and extras for user input by @jaimergp in #28
* Handle `PackagesNotFoundInChannelsError` introduced in conda v26.3.0 by @soapy1 in #54
* Add support for sharded repodata (v3) via conda's `repodata_use_shards` config by @soapy1 in #53
* CI: Build and upload noarch packages by @soapy1 in #56
* CI: Fix Windows canary build test syntax by @jezdez in #57
* CI: Build canary on linux-64 only (noarch package) by @jezdez in #59

## 0.0.6 (2026-03-16)

* Bump to py-rattler 0.23 by @jaimergp in #43

## 0.0.5 (2026-01-23)

* Update `legacy_bz2_size` to integer type by @dholth in #38
* Prevent non-requested updates of transitive dependencies by @jaimergp in #39
* Bump to `py-rattler>=0.21` and default to `PREFER_CONDA_WITH_WHL` by @jaimergp in #40

## 0.0.4 (2026-01-20)

* Use `conda>=25.5.0`, `py-rattler>=0.20`, `python>=3.10` by @jaimergp in #23
* Do not report "not found" packages as missing if already installed by @jaimergp in #25
* Prettify output, tidy up comments, add docstrings by @jaimergp in #26
* Update some deprecated imports by @jaimergp in #31
* Fix Python version changes fast-tracking by @jaimergp in #27
* CI: Update and pin GHA actions versions by @jaimergp in #24
* CI: Fix CI matrix for macOS by @jaimergp in #31
* CI: Update tests workflow from conda/conda by @jaimergp in #33
* CI: Bump setup-miniconda and remove xonsh workarounds by @jaimergp in #34
* CI: Use macos-15-intel by @jaimergp in #17

## 0.0.3 (2025-05-25)

* Use new APIs in `SparseRepoData` (`.record_count()` and `PackageFormatSelection` enum) by @jaimergp in #12
* Implements `.search()` with `SparseRepoData.load_matching_records()` by @jaimergp in #13
* Use `.record_count()` from py-rattler 0.13.1 by @jaimergp in #14
* Add conda-build recipe, fix version logic by @jaimergp in #15

## 0.0.2 (2025-05-21)

* Convert records without temporary JSON file by @jaimergp in #11

## 0.0.1 (2025-05-20)

**Prototype release**. Not meant for production.

Passes most of the test suite, except for:

- `defaults::package` does not work
- Some channel priority differences when mixing channels
