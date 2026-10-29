from __future__ import annotations

import inspect
import logging
import os
import random
import shutil
import sys
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from string import hexdigits
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING

import rattler
from conda.base.constants import REPODATA_FN
from conda.base.context import context
from conda.common.io import DummyExecutor, ThreadLimitedThreadPoolExecutor
from conda.common.url import path_to_url, remove_auth, split_anaconda_token
from conda.core.package_cache_data import PackageCacheData
from conda.core.subdir_data import SubdirData
from conda.models.channel import Channel, MultiChannel

try:
    from conda.common.serialize.json import dumps as json_dump
except ImportError:
    from conda.common.serialize import json_dump

from .utils import empty_repodata_dict, rattler_record_to_conda_record

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import Self

    from conda.common.path import PathsType
    from conda.gateways.shards import BuildRepodataSubset
    from conda.gateways.shards.typing import Shards
    from conda.models.match_spec import MatchSpec
    from conda.models.records import PackageCacheRecord, PackageRecord

    from .state import SolverInputState

log = logging.getLogger(f"conda.{__name__}")


def _root_extras(in_state: SolverInputState) -> dict[str, list[str]]:
    """
    Build the ``root_extras`` mapping for ``build_repodata_subset``
    from the extras on the requested specs and history unless pruning
    which ignores history. Root packages only.
    """
    return {
        name: list(extras)
        for name, spec in {
            **({} if in_state.prune else in_state.history),
            **in_state.requested,
        }.items()
        # `.extras` only exists on newer conda; use it once conda>=26.10 is required
        if (extras := spec.get_raw_value("extras"))
    }


# NOTE: This is a runtime compatibility check for conda versions older than 26.10, whose
# `build_repodata_subset` has no `root_extras` option. It can be deleted, passing
# `root_extras=` directly to `build_repodata_subset`, once this package requires
# `conda >=26.10.0`.
def _root_extras_kwargs(
    build_repodata_subset: BuildRepodataSubset, root_extras: dict[str, list[str]] | None
) -> dict[str, dict[str, list[str]]]:
    """
    Keyword arguments to forward ``root_extras`` to ``build_repodata_subset``.

    Returns an empty dict when there are no extras to fetch, or when the callable provided
    by conda has no ``root_extras`` parameter (conda < 26.10). Passing the keyword to an
    older conda would raise ``TypeError``, so extras are simply not fetched there.
    """
    if not root_extras:
        return {}
    try:
        if "root_extras" in inspect.signature(build_repodata_subset).parameters:
            return {"root_extras": root_extras}
    except (TypeError, ValueError):  # signature cannot be inspected
        pass
    return {}


@dataclass
class _ChannelRepoInfo:
    """Channel metadata and a record source for update solves."""

    channel: Channel | None
    repo: rattler.SparseRepoData
    full_url: str
    noauth_url: str
    local_json: str | None
    installed: Mapping[str, PackageRecord]
    package_format: rattler.PackageFormatSelection

    def package_names(self, platform: rattler.Platform) -> list[str]:
        if str(platform) != self.repo.subdir:
            return []
        return self.repo.package_names(self.package_format)

    async def fetch_package_records(
        self, platform: rattler.Platform, name: rattler.PackageName
    ) -> list[rattler.RepoDataRecord]:
        """Load conda's cached records with update build floors applied.

        Lower builds of the installed version receive an unsatisfiable
        self-dependency. Keeping these candidates visible preserves strict
        channel priority while preventing the build downgrades in issue #126.
        The changes affect only the returned records, not the cached repodata.

        https://github.com/conda/conda-rattler-solver/issues/126
        """
        if str(platform) != self.repo.subdir:
            return []
        records = self.repo.load_records(name, self.package_format)
        installed = self.installed.get(name.normalized)
        if installed and not installed.is_unmanageable:
            version = rattler.Version(installed.version)
            for record in records:
                if record.version == version and record.build_number < installed.build_number:
                    # Keep the candidate visible to strict channel priority, but make
                    # its own build number incompatible with the installed build floor.
                    record.depends = [
                        *record.depends,
                        f"{name.normalized}[build_number='>={installed.build_number}']",
                    ]
        return records


def _is_sharded_repodata_enabled():
    """
    Flag to see whether we should check for sharded repodata.
    """
    return getattr(context, "repodata_use_shards", True)


class RattlerIndexHelper:
    def __init__(
        self,
        channels: Iterable[Channel | str] | None = None,
        subdirs: Iterable[str] | None = None,
        repodata_fn: str = REPODATA_FN,
        pkgs_dirs: PathsType = (),
        in_state: SolverInputState | None = None,
        build_repodata_subset: BuildRepodataSubset | None = None,
    ):
        self._unlink_on_del: list[Path] = []

        self._channels = context.channels if channels is None else channels
        self._subdirs = context.subdirs if subdirs is None else subdirs
        self._repodata_fn = repodata_fn
        self.in_state = in_state
        self.build_repodata_subset = build_repodata_subset

        self._plan = self._plan_channels()
        self._channel_urls = tuple(
            fetch_url for _, member_urls in self._plan for fetch_url in member_urls.values()
        )
        self._index: dict[str, _ChannelRepoInfo] = {}
        self._index.update(self._load_channels(self._channel_urls))
        if pkgs_dirs:
            self._index.update(
                {info.noauth_url: info for info in self._load_pkgs_cache(pkgs_dirs)}
            )

    @classmethod
    def from_platform_aware_channel(cls, channel: Channel) -> Self:
        if not channel.platform:
            raise ValueError(f"Channel {channel} must define 'platform' attribute.")
        subdir = channel.platform
        channel = Channel(**{k: v for k, v in channel.dump().items() if k != "platform"})
        return cls(channels=(channel,), subdirs=(subdir,))

    @property
    def channels(self) -> list[Channel]:
        return [Channel(c) for c in self._channels]

    def reload_channel(self, channel: Channel) -> None:
        urls = {}
        for url in channel.urls(with_credentials=False, subdirs=self._subdirs):
            for repo_info in self._index.values():
                if repo_info.noauth_url == url:
                    log.debug("Reloading repo %s", repo_info.noauth_url)
                    urls[repo_info.full_url] = channel
                    break
        for new_repo_info in self._load_channels(urls).values():
            for repo_info in self._index.values():
                if repo_info.noauth_url == new_repo_info.noauth_url:
                    repo_info.repo.close()
                    repo_info.repo = new_repo_info.repo
                    break

    def solve_sources(
        self, *, sparse: bool = False, allow_build_downgrades: bool = False
    ) -> list[_ChannelRepoInfo | rattler.SparseRepoData | rattler.MultiSource]:
        """
        Build solver sources in channel-list order, keeping each multichannel
        member's subdirs together and appending package-cache sources last.

        Use SparseRepoData for the sparse solver. Otherwise, keep the repo
        wrappers and optionally remove their installed-build restrictions.
        """
        remaining = {}
        for url, info in self._index.items():
            if sparse:
                remaining[url] = info.repo
            elif allow_build_downgrades:
                remaining[url] = replace(info, installed={})
            else:
                remaining[url] = info

        sources = []
        for name, member_urls in self._plan:
            # Every planned URL is loaded into the index (the fetch list is the
            # plan's URLs), so the membership guard is only defensive.
            members = [remaining.pop(url) for url in member_urls if url in remaining]
            if name is None:
                sources.extend(members)
            else:
                sources.append(rattler.MultiSource(name, members))
        sources.extend(remaining.values())
        return sources

    def n_packages(
        self,
        repos: Iterable[_ChannelRepoInfo] | None = None,
        filter_: callable | None = None,
    ) -> int:
        count = 0
        if filter_ is not None:
            for info in repos or self._index.values():
                for record in info.repo.load_all_records(self._package_format):
                    if filter_(record):
                        count += 1
        else:
            for info in repos or self._index.values():
                count += info.repo.record_count(self._package_format)
        return count

    def get_info(self, key: str) -> _ChannelRepoInfo:
        if not key.startswith("file://"):
            # The conda functions (specifically remove_auth) assume the input
            # is a url; a file uri on windows with a drive letter messes them up.
            # For the rest, we remove all forms of authentication
            key = split_anaconda_token(remove_auth(key))[0]
        return self._index[key]

    def _fetch_channel(self, url: str) -> tuple[str, os.PathLike]:
        channel = Channel.from_url(url)
        if not channel.subdir:
            raise ValueError(f"Channel URLs must specify a subdir! Provided: {url}")

        if "PYTEST_CURRENT_TEST" in os.environ:
            # Workaround some testing issues - TODO: REMOVE
            # Fix conda.testing.helpers._patch_for_local_exports by removing last line
            maybe_cached = SubdirData._cache_.get((url, self._repodata_fn))
            if maybe_cached and maybe_cached._mtime == float("inf"):
                del SubdirData._cache_[(url, self._repodata_fn)]
            # /Workaround

        log.debug("Fetching %s with SubdirData.repo_fetch", channel)
        subdir_data = SubdirData(channel, repodata_fn=self._repodata_fn)
        json_path, _ = subdir_data.repo_fetch.fetch_latest_path()

        return url, json_path

    def _json_path_to_repo_info(self, url: str, json_path: str) -> _ChannelRepoInfo:
        channel = Channel.from_url(url)
        noauth_url = channel.urls(with_credentials=False, subdirs=(channel.subdir,))[0]
        json_path = Path(json_path)
        if (
            sys.platform == "win32"
            and os.environ.get("CI")
            and os.environ.get("PYTEST_CURRENT_TEST")
        ):
            # TODO: Investigate why we need this race condition workaround on Windows CI only
            random_hex = "".join(random.choices(hexdigits, k=6)).lower()
            path_copy = json_path.parent / f"{json_path.stem}.copy-{random_hex}.json"
            shutil.copy(json_path, path_copy)
            json_path = path_copy
            self._unlink_on_del.append(path_copy)
        # Keep the rattler channel unauthenticated so channel-qualified specs
        # (e.g. 'channel::package') match records cleanly; download credentials
        # are restored when converting the selected records (see to_conda_record).
        rattler_channel = rattler.Channel(noauth_url.rsplit("/", 1)[0])
        repo = rattler.SparseRepoData(rattler_channel, channel.subdir, json_path)
        return _ChannelRepoInfo(
            repo=repo,
            channel=channel,
            full_url=url,
            noauth_url=noauth_url,
            local_json=json_path,
            installed=self.in_state.installed if self.in_state else {},
            package_format=self._package_format,
        )

    def _plan_channels(
        self, channels: Iterable[Channel | str] | None = None
    ) -> list[tuple[str | None, dict[str, str]]]:
        """
        Build the channel plan with one entry per member, in channel-list
        order. Each entry pairs the multichannel name (or None for a
        standalone channel) with that member's URLs, mapping their
        unauthenticated form to their fetch form with credentials.

        The first listing of a URL owns it. Later listings of the same URL
        are skipped. Duplicate members within a listing are dropped: their
        URLs are already claimed by the first listing.

        Each member keeps its subdirs together. Separate listings remain in
        order, even when they share a multichannel name.
        """
        plan: list[tuple[str | None, dict[str, str]]] = []
        seen: set[str] = set()
        for channel in map(Channel, channels or self._channels):
            # Multichannels expand to their member channels. A standalone
            # listing of a registered multichannel member (e.g. `-c pkgs/main`
            # when `pkgs/main` is part of `defaults`) resolves to the
            # multichannel's canonical name (`defaults`) and joins that group.
            # The group name drives the priority tier and group-qualified specs
            # (e.g. `defaults::python` matches any member), not the channel
            # label: records keep their member channel's name for display
            # (`pkgs/main`).
            if isinstance(channel, MultiChannel):
                members: tuple[Channel, ...] = channel.channels
                group_name: str | None = channel.canonical_name
            else:
                members = (channel,)
                group_name = channel.canonical_name
                if group_name not in context.custom_multichannels:
                    group_name = None
            for member in members:
                noauth_urls = member.urls(with_credentials=False, subdirs=self._subdirs)
                fetch_urls = member.urls(with_credentials=True, subdirs=self._subdirs)
                # The unauthenticated URL is the identity (deduplication and
                # lookups); the fetch URL carries the member's credentials.
                # URLs claimed by an earlier listing are filtered out here, so
                # duplicate member listings contribute nothing.
                member_urls = {
                    noauth_url: fetch_url
                    for noauth_url, fetch_url in zip(noauth_urls, fetch_urls, strict=True)
                    if noauth_url not in seen
                }
                if member_urls:
                    seen.update(member_urls)
                    plan.append((group_name, member_urls))
        return plan

    def _get_root_package_from_shard(
        self, package_names: list[str]
    ) -> dict[str, _ChannelRepoInfo]:
        """
        Builds the repodata subset for a set of packages. Only applicable to sharded channels.
        """
        result: dict[str, _ChannelRepoInfo] = {}
        urls = self._channel_urls
        if self.build_repodata_subset and _is_sharded_repodata_enabled():
            urls_to_channel = {url: Channel.from_url(url) for url in urls}
            channel_data = self.build_repodata_subset(
                package_names, urls_to_channel, repodata_version=3
            )
            log.debug(
                "build_repodata_subset returned channels: %s",
                list(channel_data) if channel_data is not None else None,
            )
            if channel_data is not None:
                result.update(self._load_repo_info_from_shards(channel_data))
        return result

    def _load_channel_repo_info_shards(
        self, urls_to_channel: dict[str, Channel]
    ) -> dict[str, _ChannelRepoInfo] | None:
        """
        Load repository information from sharded repodata.

        Returns None if shards are unavailable for the given channels, in which
        case the caller falls back to the standard repodata.json path.
        """
        root_packages = (*self.in_state.installed.keys(), *self.in_state.requested)
        log.debug("build_repodata_subset root_packages: %s", root_packages)
        root_extras = _root_extras(self.in_state)
        log.debug("build_repodata_subset root_extras: %s", root_extras)
        channel_data = self.build_repodata_subset(
            root_packages,
            urls_to_channel,
            repodata_version=3,
            **_root_extras_kwargs(self.build_repodata_subset, root_extras),
        )
        log.debug(
            "build_repodata_subset returned channels: %s",
            list(channel_data) if channel_data is not None else None,
        )
        if channel_data is None:
            return None
        return self._load_repo_info_from_shards(channel_data)

    def _load_repo_info_from_shards(
        self, channel_data: dict[str, Shards]
    ) -> dict[str, _ChannelRepoInfo]:
        """
        Convert a dict[url, Shards] returned by build_repodata_subset into
        the same dict[noauth_url, _ChannelRepoInfo] format used by _load_channels.
        Each Shards object is serialised to a temporary repodata JSON file so that
        rattler.SparseRepoData can consume it without any changes to the rattler API.
        """
        index = {}
        for url, shards in channel_data.items():
            subdir = Channel.from_url(url).subdir
            repodata = empty_repodata_dict(subdir, base_url=url)
            for (key, section), record in shards.iter_records_v3():
                if section == "packages":
                    repodata["packages"][key] = record
                elif section == "packages.conda":
                    repodata["packages.conda"][key] = record
                elif section.startswith("v3."):
                    # Extract v3 package type (whl, conda, tar.bz2) from section name
                    v3_type = section[3:]  # Remove "v3." prefix
                    repodata["v3"][v3_type][key] = record
            n_packages = (
                len(repodata["packages"])
                + len(repodata["packages.conda"])
                + sum(len(group) for group in repodata["v3"].values())
            )
            log.debug(
                "_load_repo_info_from_shards: %s packages for %s",
                n_packages,
                url,
            )
            if n_packages > 0:
                log.debug(
                    "_load_repo_info_from_shards: sample filenames: %s",
                    list(repodata["packages"])[:3] + list(repodata["packages.conda"])[:3],
                )
            with NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
                f.write(json_dump(repodata))
            self._unlink_on_del.append(Path(f.name))
            info = self._json_path_to_repo_info(url, f.name)
            index[info.noauth_url] = info
        return index

    def _load_channels(self, urls: Iterable[str]) -> dict[str, _ChannelRepoInfo]:
        # Prefer sharded repodata loading if enabled and the solver provided the callable
        if self.in_state and self.build_repodata_subset and _is_sharded_repodata_enabled():
            urls_to_channel = {url: Channel.from_url(url) for url in urls}
            channel_repos_info = self._load_channel_repo_info_shards(urls_to_channel)
            if channel_repos_info is not None:
                return channel_repos_info
            log.debug("No sharded channels available. Fall back to non-sharded path.")

        # 1. Fetch URLs (if needed)
        Executor = (
            DummyExecutor
            if context.debug or context.repodata_threads == 1
            else partial(ThreadLimitedThreadPoolExecutor, max_workers=context.repodata_threads)
        )
        with Executor() as executor:
            jsons = {url: str(path) for (url, path) in executor.map(self._fetch_channel, urls)}

        # 2. Create repos in same order as `urls`
        index = {}
        for url in urls:
            info = self._json_path_to_repo_info(url, jsons[url])
            index[info.noauth_url] = info

        return index

    def _load_pkgs_cache(self, pkgs_dirs: PathsType) -> list[_ChannelRepoInfo]:
        repos = []
        subdir = next(s for s in self._subdirs if s != "noarch")
        for path in pkgs_dirs:
            path_as_url = path_to_url(path)
            package_cache_data = PackageCacheData(path)
            package_cache_data.load()
            arch = empty_repodata_dict(subdir, base_url=path_as_url)
            noarch = empty_repodata_dict("noarch", base_url=path_as_url)
            for record in package_cache_data.values():
                record: PackageCacheRecord
                if record.subdir not in self._subdirs:
                    continue
                record_data = dict(record.dump())
                for field in (
                    "sha256",
                    "track_features",
                    "license",
                    "size",
                    "url",
                    "noarch",
                    "platform",
                    "timestamp",
                ):
                    if field in record_data:
                        continue  # do not overwrite
                    value = getattr(record, field, None)
                    if value is not None:
                        record_data[field] = value
                key = "packages" if record.fn.endswith(".tar.bz2") else "packages.conda"
                if record.noarch:
                    noarch[key][record.fn] = record_data
                else:
                    arch[key][record.fn] = record_data
            for subdir_name, repodata in (("noarch", noarch), (subdir, arch)):
                with NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
                    f.write(json_dump(repodata))
                repos.append(
                    _ChannelRepoInfo(
                        repo=rattler.SparseRepoData(
                            rattler.Channel(path_as_url),
                            subdir_name,
                            f.name,
                        ),
                        channel=Channel(path_as_url),
                        full_url=path_as_url,
                        noauth_url=path_as_url,
                        local_json=f.name,
                        installed=self.in_state.installed if self.in_state else {},
                        package_format=self._package_format,
                    )
                )
                self._unlink_on_del.append(Path(f.name))
        return repos

    def _search(
        self, spec: rattler.MatchSpec, index: dict[str, _ChannelRepoInfo]
    ) -> Iterable[PackageRecord]:
        """
        Search for packages matching the given spec in the index. This function does not
        build the repodata subset for the requested spec, so it may not find packages
        that are only available in sharded channels.
        """
        for info in index.values():
            for record in info.repo.load_matching_records([spec]):
                yield rattler_record_to_conda_record(
                    record,
                    info=info,
                    add_pip_as_python_dependency=context.add_pip_as_python_dependency,
                )

    def search(
        self, spec: str | MatchSpec, search_expanded_index: bool = False
    ) -> Iterable[PackageRecord]:
        """
        Search for packages matching the given spec in the index. For channels that are sharded,
        the requested spec may not be in the loaded index. So, this function will additionally
        build the repodata subset for the requested spec. This will not update the loaded index.
        """
        spec = rattler.MatchSpec(str(spec))
        search_result = list(self._search(spec, self._index))
        if search_result:
            yield from search_result
            return

        # If there are no search results in the regular index, try to build the repodata
        # subset for the requested spec and search again.
        if search_expanded_index:
            # The packages loaded with `_get_root_package_from_shard` will have the most
            # up-to-date packages for the requested spec in sharded channels.
            extra_index = self._get_root_package_from_shard([spec.name.normalized])
            yield from self._search(spec, self._index | extra_index)

    @property
    def _package_format(self) -> rattler.PackageFormatSelection:
        return (
            rattler.PackageFormatSelection.ONLY_TAR_BZ2
            if context.use_only_tar_bz2
            else rattler.PackageFormatSelection.PREFER_CONDA_WITH_WHL
        )

    def __del__(self):
        if self._unlink_on_del:
            for info in self._index.values():
                info.repo.close()
            self._index.clear()
        for path in self._unlink_on_del:
            try:
                path.unlink(missing_ok=True)
            except Exception as exc:
                print(exc, file=sys.stderr)  # Debug
                print(self._index, file=sys.stderr)  # Debug
