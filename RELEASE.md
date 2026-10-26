<!-- edit this in https://github.com/conda/infrastructure -->

[compare]: https://github.com/conda/conda-rattler-solver/compare
[new release]: https://github.com/conda/conda-rattler-solver/releases/new
[rever docs]: https://regro.github.io/rever-docs
[Anaconda Recipes]: https://github.com/AnacondaRecipes/conda-rattler-solver-feedstock
[conda-forge]: https://github.com/conda-forge/conda-rattler-solver-feedstock
[zulip]: https://conda.zulipchat.com/#narrow/channel/480811-releases

# Release Process

> [!NOTE]
> Throughout this document are references to the version number as `MAJOR.MINOR.PATCH`, this should be replaced with the correct version number. Do **not** prefix the version with a lowercase `v`.

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
- [ ] Push the `MAJOR.MINOR.PATCH` tag and complete the release workflow
- [ ] Bump/update feedstocks
    - [ ] [Anaconda, Inc.'s feedstock][main]
    - [ ] [conda-forge feedstock][conda-forge]
- [ ] Hand off to packaging team(s)
- [ ] Announce release
    - [ ] Post on Zulip thread
```

</details>

## 2. Prepare the release notes.

1. Make sure every change in the release is represented by a news fragment in `news/` (use Markdown, **not** reStructuredText), using `news/TEMPLATE` as a guide and naming files `<PR #>-<short-slug>.md`. Merge any missing fragments into `main` with regular PRs.

    - You can utilize [GitHub's compare view][compare] to review what changes are to be included in this release.

2. Ensure the `[//]: # (current developments)` marker is present at the top of `CHANGELOG.md` on `main`.

3. Run the **Prepare release notes** workflow with `MAJOR.MINOR.PATCH` as the `version` input:

    ```bash
    $ gh workflow run prepare-release.yml --ref main -f version=MAJOR.MINOR.PATCH
    ```

    The workflow aggregates the `news/` fragments into a new `CHANGELOG.md` entry, removes the consumed fragments, computes first-time contributions, and opens a `release-notes-MAJOR.MINOR.PATCH` PR targeting `main`.

> [!NOTE]
> The workflow regenerates the release PR branch from `main` on every run. If you re-run it for the same version, repeat the contributors step below afterwards.

## 3. Prepare the contributors list.

<details>
<summary><h2>Rever steps</h2></summary>

Install [`rever`][rever docs] using whatever your project defines (e.g., a conda environment or a pixi `release` environment). For example, [conda-pypi](https://github.com/conda/conda-pypi) uses `pixi run -e release rever ...`; other projects may use `conda create -n rever conda-forge::rever` and run `rever` directly.

1. Clone and `cd` into the repository if you haven't done so already:

    ```bash
    $ git clone git@github.com:conda/conda-rattler-solver.git
    $ cd conda-rattler-solver
    ```

2. Check out the release PR branch:

    ```bash
    $ git fetch origin
    $ git switch release-notes-MAJOR.MINOR.PATCH
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

4. Push the changes directly to the release PR branch:

    ```bash
    $ git push origin HEAD
    ```

</details>

## 4. Wait for review and approval of the release PR.

## 5. Merge the release PR and push the version tag.

Follow the [repository-specific publishing instructions](RELEASE_PUBLISHING.md) to complete any required setup before pushing the tag.

After the release PR is reviewed and merged, fetch `main`:

```bash
git fetch origin main
```

Confirm that `origin/main` is the intended release commit and that its required checks have passed. Then [create the release][new release] and **save as draft**:

| Field | Value |
|---|---|
| Choose a tag | `MAJOR.MINOR.PATCH` |
| Target | `main` |
| Body | copy/paste the `MAJOR.MINOR.PATCH` entry from `CHANGELOG.md` |

> **Note:** Leave this release as a draft. The publishing workflow publishes it after its package publication steps succeed.

Create and push a signed version tag:

```bash
git tag -s MAJOR.MINOR.PATCH origin/main -m "Release MAJOR.MINOR.PATCH"
git push origin MAJOR.MINOR.PATCH
```

Follow the publishing workflow and complete any required approvals. The workflow publishes the draft release after its package publication steps succeed. Verify the published assets before updating feedstocks.

## 6. Bump [Anaconda Recipes][Anaconda Recipes] and [conda-forge][conda-forge] feedstocks to use `MAJOR.MINOR.PATCH`.

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

## 7. Hand off to Anaconda's packaging team.

> [!NOTE]
> This step should NOT be done past Thursday morning EST; please start the process on a Monday, Tuesday, or Wednesday instead in order to avoid any potential debugging sessions over evenings or weekends.

<details>
<summary>Internal process</summary>

1. Open packaging request in #package_requests Slack channel, include links to the Release PR and feedstock PRs.

2. Message packaging team/PM to let them know that a release has occurred and that you are the release manager.

</details>

## 8. Announce the release.

Post the release announcement on the Zulip thread in [#releases][zulip].
