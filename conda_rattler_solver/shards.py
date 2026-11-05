from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import rattler
from conda.models.channel import Channel

if TYPE_CHECKING:
    from collections.abc import Iterable

    from conda.gateways.shards.typing import Shards


_FORMATS = {
    "packages": ".tar.bz2",
    "v3.tar.bz2": ".tar.bz2",
    "v3.whl": ".whl",
    "packages.conda": ".conda",
    "v3.conda": ".conda",
}
_DEFAULT_FORMAT = rattler.PackageFormatSelection.PREFER_CONDA
_ARCHIVE_BASENAME = re.compile(r"[A-Za-z0-9_.+@!-]+")


class ShardedRepoData:
    """Keep conda's shard records in memory and convert them when requested."""

    def __init__(self, url: str, shards: Shards):
        channel = Channel.from_url(url)
        self.subdir = channel.subdir
        noauth_url = channel.urls(with_credentials=False, subdirs=(self.subdir,))[0]
        self._channel = noauth_url.rsplit("/", 1)[0] + "/"
        self._url = url.rstrip("/") + "/"
        self._archive_url = urljoin(self._url, "./")
        self._records = {}
        self._names = {}
        for (key, section), record in shards.iter_records_v3():
            if section not in _FORMATS:
                continue
            stem = key if section.startswith("v3.") else key.removesuffix(_FORMATS[section])
            name = stem.rsplit("-", 2)[0].lower()
            records = self._records.setdefault(name, {})
            if section.startswith("v3."):
                records[stem + _FORMATS[section]] = record
            else:
                # V3 takes precedence regardless of the shard iteration order.
                records.setdefault(key, record)

    def _selected(self, name, package_format):
        formats = rattler.PackageFormatSelection
        allowed = {
            formats.ONLY_TAR_BZ2: (".tar.bz2",),
            formats.ONLY_CONDA: (".conda",),
            formats.PREFER_CONDA: (".tar.bz2", ".conda"),
            formats.PREFER_CONDA_WITH_WHL: (".tar.bz2", ".conda", ".whl"),
            formats.BOTH: (".tar.bz2", ".conda"),
        }[package_format]
        selected = {}
        records = self._records.get(name, {})
        # Later entries replace older repodata and less preferred archive formats.
        for suffix in (".tar.bz2", ".whl", ".conda"):
            if suffix not in allowed:
                continue
            for filename in records:
                if filename.endswith(suffix):
                    key = (
                        filename
                        if package_format == formats.BOTH
                        else filename.removesuffix(suffix)
                    )
                    selected[key] = filename
        return selected.values()

    def package_names(self, package_format=_DEFAULT_FORMAT) -> list[str]:
        if package_format not in self._names:
            self._names[package_format] = sorted(
                name for name in self._records if self._selected(name, package_format)
            )
        return list(self._names[package_format])

    def record_count(self, package_format=_DEFAULT_FORMAT) -> int:
        return sum(len(self._selected(name, package_format)) for name in self._records)

    def load_records(self, name, package_format=_DEFAULT_FORMAT) -> list[rattler.RepoDataRecord]:
        """Read independent records without populating the solver's native cache."""
        name = name.normalized if isinstance(name, rattler.PackageName) else name.lower()
        stored = self._records.get(name, {})
        records = []
        for filename in self._selected(name, package_format):
            record = stored[filename]
            if isinstance(record, rattler.RepoDataRecord):
                record = rattler.RepoDataRecord(
                    record, record.file_name, record.url, record.channel
                )
            else:
                record = self._convert(filename, record)
            records.append(record)
        return records

    def records_for_solve(
        self, name, package_format=_DEFAULT_FORMAT
    ) -> list[rattler.RepoDataRecord]:
        """Borrow cached records for py-rattler, which shares their Rust allocations.

        Callers must copy a record before changing it in Python.
        """
        name = name.normalized if isinstance(name, rattler.PackageName) else name.lower()
        records = []
        cached = self._records.get(name, {})
        for filename in self._selected(name, package_format):
            record = cached[filename]
            if not isinstance(record, rattler.RepoDataRecord):
                # Release our raw metadata reference when the native record replaces it.
                record = cached[filename] = self._convert(filename, record)
            records.append(record)
        return records

    def load_all_records(self, package_format=_DEFAULT_FORMAT) -> list[rattler.RepoDataRecord]:
        return [
            record
            for name in self.package_names(package_format)
            for record in self.load_records(name, package_format)
        ]

    def load_matching_records(
        self,
        specs: Iterable[rattler.MatchSpec],
        package_format=rattler.PackageFormatSelection.PREFER_CONDA_WITH_WHL,
    ) -> list[rattler.RepoDataRecord]:
        specs = tuple(specs)
        names = set()
        for spec in specs:
            name = spec.name.as_package_name()
            if name is None:
                names.update(self.package_names(package_format))
                break
            names.add(name.normalized)
        matches = []
        for name in sorted(names):
            stored = self._records.get(name, {})
            for filename in self._selected(name, package_format):
                record = stored[filename]
                shared = isinstance(record, rattler.RepoDataRecord)
                if not shared:
                    record = self._convert(filename, record)
                if any(spec.matches(record) for spec in specs):
                    if shared:
                        record = rattler.RepoDataRecord(
                            record, record.file_name, record.url, record.channel
                        )
                    matches.append(record)
        return matches

    def _convert(self, filename, raw) -> rattler.RepoDataRecord:
        kwargs = {
            field: raw[field]
            for field in (
                "arch",
                "platform",
                "depends",
                "constrains",
                "size",
                "features",
                "legacy_bz2_size",
                "license",
                "license_family",
                "python_site_packages_path",
                "extra_depends",
                "flags",
            )
            if field in raw
        }
        for field in ("sha256", "md5", "legacy_bz2_md5", "attestations_sha256"):
            if raw.get(field):
                kwargs[field] = bytes.fromhex(raw[field])
        noarch = raw.get("noarch") or None
        record = rattler.PackageRecord(
            name=raw["name"],
            version=raw["version"],
            build=rattler.BuildString.new_unchecked(raw["build"]),
            build_number=raw["build_number"],
            subdir=raw.get("subdir") or self.subdir,
            noarch=noarch,
            **kwargs,
        )
        # The constructor infers these from subdir, unlike repodata deserialization.
        record.arch = raw.get("arch")
        record.platform = raw.get("platform")
        track_features = raw.get("track_features", [])
        if isinstance(track_features, str):
            track_features = [part.strip() for part in track_features.replace(",", " ").split(" ")]
        record.track_features = track_features
        for field in ("timestamp", "indexed_timestamp"):
            value = raw.get(field)
            if value is not None:
                if field == "indexed_timestamp" or value > 253_402_300_799:
                    value /= 1000
                setattr(record, field, datetime.fromtimestamp(value, timezone.utc))
        if filename.endswith(".whl"):
            package_url = urljoin(self._url, raw["url"])
        elif _ARCHIVE_BASENAME.fullmatch(filename):
            # Ordinary archive names only need the already-resolved channel prefix.
            package_url = self._archive_url + filename
        else:
            package_url = urljoin(self._url, filename)
        return rattler.RepoDataRecord(record, filename, package_url, self._channel)

    def close(self) -> None:
        pass
