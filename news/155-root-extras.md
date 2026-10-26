### Enhancements

* Pass `root_extras` to conda's `build_repodata_subset` so sharded repodata fetching retrieves only the root-level extras (`extra_depends` groups) requested by the user both now and in the past. Extras of dependencies are not traversed. Requires conda>=26.10 and py-rattler>=0.27 to take effect; with older versions extras are not fetched. (#155)

### Bug fixes

* <news item>

### Deprecations

* <news item>

### Docs

* <news item>

### Other

* <news item>
