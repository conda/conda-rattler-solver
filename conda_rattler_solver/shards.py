from __future__ import annotations

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


class ShardedRepoData:
    """Keep conda's shard records in memory and convert them when requested."""

    def __init__(self, url: str, shards: Shards):
        channel = Channel.from_url(url)
        self.subdir = channel.subdir
        noauth_url = channel.urls(with_credentials=False, subdirs=(self.subdir,))[0]
        self._channel = noauth_url.rsplit("/", 1)[0] + "/"
        self._url = url.rstrip("/") + "/"
        self._records = {}
        self._converted = {}
        for (key, section), record in shards.iter_records_v3():
            if section not in _FORMATS:
                continue
            stem = key if section.startswith("v3.") else key.removesuffix(_FORMATS[section])
            name = stem.rsplit("-", 2)[0].lower()
            self._records.setdefault(name, {})[section, stem] = record

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
        for section, suffix in _FORMATS.items():
            if suffix not in allowed:
                continue
            for (record_section, stem), record in records.items():
                if record_section == section:
                    key = (stem, suffix) if package_format == formats.BOTH else stem
                    selected[key] = (section, stem, record)
        return selected.values()

    def package_names(self, package_format=_DEFAULT_FORMAT) -> list[str]:
        return sorted(name for name in self._records if self._selected(name, package_format))

    def record_count(self, package_format=_DEFAULT_FORMAT) -> int:
        return sum(len(self._selected(name, package_format)) for name in self._records)

    def load_records(self, name, package_format=_DEFAULT_FORMAT) -> list[rattler.RepoDataRecord]:
        name = name.normalized if isinstance(name, rattler.PackageName) else name.lower()
        records = []
        for section, stem, raw in self._selected(name, package_format):
            key = (section, stem)
            if key not in self._converted:
                self._converted[key] = self._convert(section, stem, raw)
            record = self._converted[key]
            # Update solves modify dependencies. Every caller needs its own record.
            records.append(
                rattler.RepoDataRecord(record, record.file_name, record.url, record.channel)
            )
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
        return [
            record
            for name in sorted(names)
            for record in self.load_records(name, package_format)
            if any(spec.matches(record) for spec in specs)
        ]

    def _convert(self, section, stem, raw) -> rattler.RepoDataRecord:
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
        filename = stem + _FORMATS[section]
        package_url = raw["url"] if section == "v3.whl" else filename
        return rattler.RepoDataRecord(
            record, filename, urljoin(self._url, package_url), self._channel
        )

    def close(self) -> None:
        pass
