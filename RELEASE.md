[compare]: https://github.com/conda/conda-rattler-solver/compare
[new release]: https://github.com/conda/conda-rattler-solver/releases/new
[release docs]: https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes
[rever docs]: https://regro.github.io/rever-docs
[Anaconda Recipes]: https://github.com/AnacondaRecipes/conda-rattler-solver-feedstock
[conda-forge]: https://github.com/conda-forge/conda-rattler-solver-feedstock
[zulip]: https://conda.zulipchat.com/#narrow/channel/480811-releases

# Release Process

> [!NOTE]
> Throughout this document are references to the version number as `MAJOR.MINOR.PATCH`, this should be replaced with the correct version number. Do **not** prefix the version with a lowercase `v`.

The [release workflow](.github/workflows/release.yml) starts when a version tag is pushed. It builds and checks the distributions, records their provenance, attaches them to a draft GitHub release, publishes the same files to PyPI, and publishes the GitHub release last. Keep the release as a draft until the workflow finishes.

Before the first PyPI release, confirm its trusted publisher uses owner `conda`, repository `conda-rattler-solver`, workflow `release.yml`, and environment `pypi`. The GitHub `pypi` environment requires approval and permits version tags only.

## 1. Open the release issue.

Create a release issue using the template below. After creating it, pin it for easy access.

<details>
<summary><h3>Release Template</h3></summary>

#### Title:
```markdown
Release `MAJOR.MINOR.PATCH`
```

#### Body:
```markdown
### Summary

Placeholder for `conda-rattler-solver MAJOR.MINOR.PATCH` release.

| Pilot | <pilot> |
|---|---|
| Co-pilot | <copilot> |

### Tasks

[milestone]: https://github.com/conda/conda-rattler-solver/milestone/<milestone>
[process]: https://github.com/conda/conda-rattler-solver/blob/main/RELEASE.md
[releases]: https://github.com/conda/conda-rattler-solver/releases
[main]: https://github.com/AnacondaRecipes/conda-rattler-solver-feedstock
[conda-forge]: https://github.com/conda-forge/conda-rattler-solver-feedstock
[zulip]: https://conda.zulipchat.com/#narrow/channel/480811-releases

- [ ] [Complete outstanding PRs][milestone]
- [ ] Create release PR (see [release process][process])
- [ ] Create Zulip thread on [#releases][zulip]
    - [ ] Announce `MAJOR.MINOR.PATCH` in-progress
- [ ] [Publish release][releases]
- [ ] Bump/update feedstocks
    - [ ] [Anaconda, Inc.'s feedstock][main]
    - [ ] [conda-forge feedstock][conda-forge]
- [ ] Hand off to packaging team(s)
- [ ] Announce release
    - [ ] Post on Zulip thread
```

</details>

## 2. Run rever.

<details>
<summary><h2>Rever steps</h2></summary>

Install [`rever`][rever docs] using whatever your project defines (e.g., a conda environment or a pixi `release` environment). For example, [conda-pypi](https://github.com/conda/conda-pypi) uses `pixi run -e release rever ...`; other projects may use `conda create -n rever conda-forge::rever` and run `rever` directly.

1. Clone and `cd` into the repository if you haven't done so already:

    ```bash
    $ git clone git@github.com:conda/conda-rattler-solver.git
    $ cd conda-rattler-solver
    ```

2. Fetch the latest changes and create a versioned branch off `main` for the release PR:

    ```bash
    $ git fetch origin
    $ git switch -c changelog-MAJOR.MINOR.PATCH --no-track origin/main
    ```

3. Run `rever --activities authors --force MAJOR.MINOR.PATCH`:

    > **Note:**
    > Include `--force` when re-running any rever command for the same version; without it, rever skips already-completed activities.

    ```bash
    $ rever --activities authors --force MAJOR.MINOR.PATCH
    ```

    - If rever reports unknown authors, add or update entries in `.authors.yml` (new contributors get a new entry; existing contributors using a new name/email get an `aliases`/`alternate_emails` addition).

    - Verify the result with:

        ```bash
        $ git shortlog -se
        ```

      Compare this list against `AUTHORS.md` and repeat until they match.

4. Review news snippets in `news/` (use Markdown, **not** reStructuredText). Add snippets for any undocumented changes using the `news/TEMPLATE` as a guide, naming files `<PR #>-<short-slug>.md`.

    - You can utilize [GitHub's compare view][compare] to review what changes are to be included in this release.

    - Commit when satisfied:

        ```bash
        $ git add news/
        $ git commit -m "Update news"
        ```

5. Ensure the `[//]: # (current developments)` marker is present at the top of `CHANGELOG.md`, then run `rever --activities changelog --force MAJOR.MINOR.PATCH`:

    ```bash
    $ rever --activities changelog --force MAJOR.MINOR.PATCH
    ```

    - If this succeeds, undo the commit so both activities can be run together in the next step:

        ```bash
        $ git reset --hard HEAD~1
        ```

6. Run both activities together so the contributor list is embedded in the changelog entry:

    ```bash
    $ rever --force MAJOR.MINOR.PATCH
    ```

7. Use [GitHub's auto-generated release notes][new release] to identify first-time contributors and add `made their first contribution in <URL>` next to their entry in the Contributors section of `CHANGELOG.md`. See [GitHub docs][release docs] for how to auto-generate the release notes. Commit:

    ```bash
    $ git add CHANGELOG.md
    $ git commit -m "Add first-time contributions"
    ```

8. Push the versioned branch:

    ```bash
    $ git push -u origin HEAD
    ```

9. Open the Release PR targeting `main`:

    ```markdown
    ## Description

    ✂️ snip snip ✂️ the making of a new release.

    Xref #<RELEASE ISSUE>
    ```

10. [Create][new release] the release and **save as draft**:

    | Field | Value |
    |---|---|
    | Choose a tag | `MAJOR.MINOR.PATCH` |
    | Target | `main` |
    | Body | copy/paste from `CHANGELOG.md` |

    > **Note:** Leave the release as a draft. The workflow preserves these notes and publishes the release after the distributions reach PyPI.

</details>

## 3. Wait for review and approval of the release PR.

## 4. Merge the release PR and push the version tag.

After the release PR is reviewed and merged, confirm the intended commit has passed its required checks. Fetch it and push a signed version tag:

```bash
git fetch origin main
git tag -s MAJOR.MINOR.PATCH origin/main -m "Release MAJOR.MINOR.PATCH"
git push origin MAJOR.MINOR.PATCH
```

Follow the release workflow and approve the `pypi` deployment after checking the tag and draft assets. The workflow publishes GitHub only after PyPI succeeds. Confirm both services contain the expected wheel and source archive before updating feedstocks.

If a publication job fails, rerun the failed jobs to reuse the already-built distributions. Existing draft assets are accepted only when their bytes match. Do not replace published files or move a released tag. For a partial PyPI upload, inspect which files were accepted before retrying.

## 5. Bump [Anaconda Recipes][Anaconda Recipes] and [conda-forge][conda-forge] feedstocks to use `MAJOR.MINOR.PATCH`.

Open a PR to bump the Anaconda Recipes feedstock.

For conda-forge, the `regro-cf-autotick-bot` will usually open a PR automatically. Review and merge it (or push fixes to the autotick branch if needed).

> [!NOTE]
> Conda-forge's PRs will be auto-created via the `regro-cf-autotick-bot`. Follow the instructions below if any changes need to be made to the recipe that were not automatically added (these instructions are only necessary for anyone who is _not_ a conda-forge feedstock maintainer, since maintainers can push changes directly to the autotick branch):
> - Create a new branch based off of autotick's branch (autotick's branches usually use the `regro-cf-autotick-bot:XX.YY.[$patch_number]_[short hash]` syntax)
> - Add any changes via commits to that new branch
> - Open a new PR and push it against the `main` branch
>
> Make sure to include a comment on the original `autotick-bot` PR that a new pull request has been created, in order to avoid duplicating work!  `regro-cf-autotick-bot` will close the auto-created PR once the new PR is merged.
>
> For more information about this process, please read the ["Pushing to regro-cf-autotick-bot branch" section of the conda-forge documentation](https://conda-forge.org/docs/maintainer/updating_pkgs.html#pushing-to-regro-cf-autotick-bot-branch).

## 6. Hand off to Anaconda's packaging team.

> [!NOTE]
> This step should NOT be done past Thursday morning EST; please start the process on a Monday, Tuesday, or Wednesday instead in order to avoid any potential debugging sessions over evenings or weekends.

<details>
<summary>Internal process</summary>

1. Open packaging request in #package_requests Slack channel, include links to the Release PR and feedstock PRs.

2. Message packaging team/PM to let them know that a release has occurred and that you are the release manager.

</details>

## 7. Announce the release.

Post the release announcement on the Zulip thread in [#releases][zulip].
