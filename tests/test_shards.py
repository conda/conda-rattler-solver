from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import rattler

from conda_rattler_solver.shards import ShardedRepoData

URL = "https://example.org/channel/linux-64"


def record(name="example", **kwargs):
    return {"name": name, "version": "1.0", "build": "0", "build_number": 0, **kwargs}


def shard_source(entries, url=URL):
    return ShardedRepoData(url, SimpleNamespace(iter_records_v3=lambda: iter(entries)))


def sparse_source(tmp_path, entries, url=URL):
    repodata = {
        "info": {"subdir": "linux-64", "base_url": url},
        "packages": {},
        "packages.conda": {},
        "v3": {"conda": {}, "tar.bz2": {}, "whl": {}},
    }
    for (key, section), data in entries:
        if section.startswith("v3."):
            repodata["v3"][section[3:]][key] = data
        else:
            repodata[section][key] = data
    path = tmp_path / "repodata.json"
    path.write_text(json.dumps(repodata))
    return rattler.SparseRepoData(rattler.Channel("https://example.org/channel"), "linux-64", path)


def snapshot(records):
    result = []
    for item in records:
        data = json.loads(item.to_json())
        # Rattler preserves seconds or milliseconds in JSON but exposes the same datetime.
        if "timestamp" in data:
            data["timestamp"] = item.timestamp.isoformat() if item.timestamp else 0
        if "noarch" in data:
            data["noarch"] = "python" if item.noarch.python else "generic"
        result.append(data)
    return sorted(result, key=lambda item: item["fn"])


@pytest.mark.parametrize("package_format", list(rattler.PackageFormatSelection))
def test_format_selection_matches_sparse(tmp_path, package_format):
    entries = [
        (("example-1.0-0.tar.bz2", "packages"), record(license="legacy tar")),
        (("example-1.0-0.conda", "packages.conda"), record(license="legacy conda")),
        (("example-1.0-0", "v3.tar.bz2"), record(license="v3 tar")),
        (("example-1.0-0", "v3.conda"), record(license="v3 conda")),
        (("example-1.0-0", "v3.whl"), record(url="https://wheels.example.org/example.whl")),
        (("wheel-1.0-0", "v3.whl"), record("wheel", url="../wheels/wheel.whl")),
        (("tar-1.0-0.tar.bz2", "packages"), record("tar")),
    ]
    source = shard_source(entries)
    with sparse_source(tmp_path, entries) as sparse:
        assert snapshot(source.load_all_records(package_format)) == snapshot(
            sparse.load_all_records(package_format)
        )
        assert sorted(source.package_names(package_format)) == sorted(
            sparse.package_names(package_format)
        )
        assert source.record_count(package_format) == sparse.record_count(package_format)
        assert snapshot(source.load_records(rattler.PackageName("example"), package_format)) == (
            snapshot(sparse.load_records("example", package_format))
        )


@pytest.mark.parametrize("timestamp", [0, 1_640_000_000, 1_640_000_000_123])
def test_metadata_matches_sparse(tmp_path, timestamp):
    entries = [
        (
            ("example-1.0-0.conda", "packages.conda"),
            record(
                depends=["dependency >=1"],
                constrains=["other <2"],
                extra_depends={"test": ["pytest"]},
                flags=["test_flag"],
                track_features="mkl, feature",
                features="legacy_feature",
                sha256="12" * 32,
                md5="34" * 16,
                legacy_bz2_md5="56" * 16,
                legacy_bz2_size=123,
                attestations_sha256="78" * 32,
                size=456,
                license="BSD-3-Clause",
                license_family="BSD",
                timestamp=timestamp,
                indexed_timestamp=1_650_000_000_123,
                python_site_packages_path="lib/python3.14/site-packages",
            ),
        )
    ]
    with sparse_source(tmp_path, entries) as sparse:
        assert snapshot(shard_source(entries).load_all_records()) == snapshot(
            sparse.load_all_records()
        )


@pytest.mark.parametrize(
    "section,key,metadata",
    [
        ("packages", "example-1.0-0.tar.bz2", {}),
        ("v3.tar.bz2", "example-1.0-0", {}),
        ("v3.conda", "example-1.0-0", {}),
        ("v3.whl", "example-1.0-0", {"url": "../wheels/example-py3-none-any.whl"}),
        (
            "v3.whl",
            "example-1.0-0",
            {"url": "https://cdn.example.org/wheels/example-py3-none-any.whl"},
        ),
    ],
)
def test_urls_and_filenames_match_sparse(tmp_path, section, key, metadata):
    entries = [((key, section), record(**metadata))]
    package_format = rattler.PackageFormatSelection.PREFER_CONDA_WITH_WHL
    with sparse_source(tmp_path, entries) as sparse:
        assert snapshot(shard_source(entries).load_all_records(package_format)) == snapshot(
            sparse.load_all_records(package_format)
        )


def test_records_are_independent_between_loads():
    entries = [(("example-1.0-0.conda", "packages.conda"), record(depends=["dep >=1"]))]
    source = shard_source(entries)
    first = source.load_records("example")[0]
    first.depends = ["unavailable"]
    assert source.load_records("example")[0].depends == ["dep >=1"]
    assert source.load_all_records()[0].depends == ["dep >=1"]


def test_search_filters_records():
    source = shard_source(
        [
            (("example-1.0-0.conda", "packages.conda"), record()),
            (("example-2.0-0", "v3.whl"), record(version="2.0", url="example.whl")),
            (("other-1.0-0.conda", "packages.conda"), record("other")),
        ]
    )
    matches = source.load_matching_records([rattler.MatchSpec("example >=2")])
    assert [item.file_name for item in matches] == ["example-2.0-0.whl"]
    assert source.load_records("missing") == []
    matches = source.load_matching_records([rattler.MatchSpec("ex*", exact_names_only=False)])
    assert [item.file_name for item in matches] == ["example-2.0-0.whl", "example-1.0-0.conda"]


def test_authenticated_source_preserves_package_url():
    url = "https://user:password@example.org/t/token/channel/linux-64"
    source = shard_source([(("example-1.0-0.conda", "packages.conda"), record())], url)
    loaded = source.load_all_records()[0]
    assert loaded.channel == "https://example.org/channel/"
    assert loaded.url == url + "/example-1.0-0.conda"


@pytest.mark.parametrize("noarch", [None, False, True, "generic", "python"])
def test_legacy_record_fields_match_sparse(tmp_path, noarch):
    entries = [
        (
            ("example-1.0-0.conda", "packages.conda"),
            record(build="legacy@build", noarch=noarch, subdir="", track_features=["mkl"]),
        )
    ]
    with sparse_source(tmp_path, entries) as sparse:
        assert snapshot(shard_source(entries).load_all_records()) == snapshot(
            sparse.load_all_records()
        )


def test_invalid_unrequested_records_are_not_converted():
    source = shard_source(
        [
            (("example-1.0-0.conda", "packages.conda"), record()),
            (("unused-1.0-0.conda", "packages.conda"), record("unused", version="invalid!")),
        ]
    )
    assert source.package_names() == ["example", "unused"]
    assert source.record_count() == 2
    assert source.load_records("example")[0].name.normalized == "example"
    assert len(source.load_matching_records([rattler.MatchSpec("example")])) == 1
    with pytest.raises(rattler.exceptions.InvalidVersionError):
        source.load_records("unused")
