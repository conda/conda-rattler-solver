# More resources

If you want to learn more about conda-rattler-solver and the projects it is
built on, we have compiled a list of additional material you can check:

* [rattler](https://github.com/conda/rattler), the Rust library that powers the
  solver, and its Python bindings [py-rattler](https://conda.github.io/rattler/py-rattler/)
* [resolvo](https://github.com/prefix-dev/resolvo), the underlying dependency
  solver, which implements a CDCL-style SAT solver inspired by
  [libsolv](https://github.com/openSUSE/libsolv)
* [pixi](https://pixi.sh), the package manager that uses the same solver
% TODO: switch the "Solvers" link from "latest" to "stable" once a conda release
% that includes the page (added after 26.9) has been published.

* The ["Solvers" page](https://docs.conda.io/projects/conda/en/latest/user-guide/concepts/solvers.html)
  in the conda user guide, which compares the available solver plugins and
  explains how to switch between them
* The ["Deep dive: solvers" guide](https://docs.conda.io/projects/conda/en/stable/dev-guide/deep-dives/solvers.html)
  in the conda documentation
* [conda-libmamba-solver](https://conda.github.io/conda-libmamba-solver/), the
  other solver plugin for conda, and its
  ["libmamba vs classic"](https://conda.github.io/conda-libmamba-solver/user-guide/libmamba-vs-classic/)
  page, which explains many concepts that also apply here
* [Bencher performance benchmarks](https://bencher.dev/perf/conda-rattler-solver)
  for conda-rattler-solver
