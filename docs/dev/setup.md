# How to set up your development environment

## With Pixi

% Keep this section in sync with the "Setup" section of CONTRIBUTING.md.

The development workflow is built around [Pixi](https://pixi.sh). Install
[Pixi](https://pixi.sh/latest/installation/) and Git, then clone this
repository alongside `conda/conda`, whose test data is used by the test and
benchmark tasks:

```shell
git clone https://github.com/conda/conda.git
git clone https://github.com/conda/conda-rattler-solver.git
cd conda-rattler-solver
```

The tasks expect conda's test data at `../conda/tests/data`. Pixi installs the
locked dependencies and an editable copy of this repository when you run them.
For example, to run the test suite with Python 3.13:

```shell
pixi run --locked -e test-py313 test
```

The available environments are defined in `pyproject.toml`. The ones you will
use most often are:

| Environment                              | Purpose                                            |
| ---------------------------------------- | -------------------------------------------------- |
| `test-py311`, `test-py312`, `test-py313`, `test-py314` | Run the tests and benchmarks on a given Python version |
| `lint`                                   | Run the pre-commit hooks                           |
| `docs`                                   | Build this documentation                           |
| `build`                                  | Build the conda package from `recipe/`             |

See [Typical development workflows](workflows) for the tasks each one offers.

## With `devcontainer` in VS Code

A `devcontainer` configuration is bundled in this repository for a disposable
Linux environment. You'll need Docker and VS Code with the
[Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers):

1. Clone `conda/conda` and `conda/conda-rattler-solver` to your preferred
   locations, for example, `~/devel/conda` and `~/devel/conda-rattler-solver`.
   The location does not matter as long as both repositories have the same
   parent directory.
2. Open your `conda-rattler-solver` clone with VS Code.
3. Connect to the DevContainer image via the bottom-left menu (<kbd>❱❰</kbd>)
   and click on "Reopen in Container". The image is based on Miniforge.
4. The image will be built and after a couple of minutes, you'll be dropped
   into a Bash shell. Since the local repositories are mounted, you can make
   modifications to the source live, and they will be reflected in the Docker
   instance automatically. Run `pytest` or `conda` as needed, no need to reload
   Docker!
5. If the development environment breaks, click again on <kbd>❱❰</kbd> and,
   this time, choose "Rebuild container". You might need to retry a couple of
   times.

## With regular Docker

You can reuse the devcontainer scripts with regular Docker too.

1. Clone `conda/conda` and `conda/conda-rattler-solver` to your preferred
   locations, as above.
2. Start a new Docker instance with this command. Adjust the local mounts as
   necessary.

   ```bash
   docker run -it --rm \
     -v ~/devel/conda:/workspaces/conda \
     -v ~/devel/conda-rattler-solver:/workspaces/conda-rattler-solver \
     condaforge/miniforge3:latest \
     bash
   ```

3. Run the `post_create` and `post_start` scripts:

   ```bash
   bash /workspaces/conda-rattler-solver/.devcontainer/post_create.sh
   bash /workspaces/conda-rattler-solver/.devcontainer/post_start.sh
   ```

## Manual setup

If you prefer to manage the environment yourself, be careful with overwriting
your existing `conda` installations, especially when it comes to shell
initialisation.

1. Get yourself familiar with the
   ["Development environment" guide for `conda` itself][conda_dev].

2. Fork and clone the conda-rattler-solver repository to your preferred
   location:

   ```bash
   git clone "git@github.com:$YOUR_USERNAME/conda-rattler-solver" "$REPO_LOCATION"
   cd "$REPO_LOCATION"
   ```

3. Install the required dependencies for conda-rattler-solver:

   ```bash
   conda install \
     --file "$REPO_LOCATION"/dev/requirements.txt \
     --file "$REPO_LOCATION"/tests/requirements.txt
   ```

4. Install conda-rattler-solver in editable mode:

   ```bash
   cd "$REPO_LOCATION"
   python -m pip install --no-deps -e .
   ```

## Debugging

Once you have followed the steps above you may need to investigate the state at
a particular point. Insert a
[`breakpoint()`](https://docs.python.org/3/library/pdb.html) within the code
and run a test or `conda` directly to hit the breakpoint.

Most of the solving logic is in Rust code, inside the `rattler` and `resolvo`
libraries. The Python side of this plugin is responsible for translating
conda's view of the request (installed packages, history, pins, and channel configuration) into `py-rattler` objects, running the solve, and translating
the result back. If you suspect a bug in the solver itself, we suggest investigating
against the [`rattler`](https://github.com/conda/rattler) repository.

<!-- LINKS -->

[conda_dev]: https://docs.conda.io/projects/conda/en/latest/dev-guide/development-environment.html
