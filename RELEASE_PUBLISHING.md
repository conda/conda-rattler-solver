# Publishing a release

Follow [RELEASE.md](RELEASE.md) to prepare the release PR and draft GitHub release.

The [release workflow](.github/workflows/release.yml) starts when a version tag is
pushed. It builds and checks the distributions, records their provenance, attaches
them to the draft while preserving its notes, publishes the same files to PyPI,
and publishes the GitHub release last. Keep the release as a draft until the
workflow finishes.

Before the first PyPI release, confirm its trusted publisher uses owner `conda`,
repository `conda-rattler-solver`, workflow `release.yml`, and environment `pypi`.
The GitHub `pypi` environment requires approval and permits version tags only.

After pushing the tag, approve the `pypi` deployment after checking the tag and
draft assets. Confirm both PyPI and GitHub contain the expected wheel and source
archive before updating feedstocks.

If a publication job fails, rerun the failed jobs to reuse the already-built
distributions. Existing draft assets are accepted only when their bytes match.
Do not replace published files or move a released tag. For a partial PyPI upload,
inspect which files were accepted before retrying.
