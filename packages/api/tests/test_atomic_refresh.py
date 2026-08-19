"""Concurrency, failure, and rollover tests for atomic API snapshots."""

import hashlib
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import data_loader
from app.data_loader import (
    AppDataSnapshot,
    ShootingsSnapshot,
    ShootingVersionSnapshot,
)
from app.routers.shootings import router as shootings_router
from dashboard_utils.boundary_releases import (
    BOUNDARY_JOIN_FIELDS,
    boundary_release_key,
    compute_boundary_release_id,
)


class MemoryS3:
    """Exact-byte S3 stand-in for release-pointer integration tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.get_calls: list[str] = []
        self.block_key: str | None = None
        self.get_started: Event | None = None
        self.allow_get: Event | None = None

    def put(self, key: str, body: bytes, etag: str) -> None:
        self.objects[key] = (body, etag)

    def get_object(self, *, Bucket: str, Key: str):
        del Bucket
        self.get_calls.append(Key)
        if Key == self.block_key:
            if self.get_started is None or self.allow_get is None:
                raise RuntimeError("Blocked MemoryS3 read requires synchronization events")
            self.get_started.set()
            if not self.allow_get.wait(timeout=2):
                raise TimeoutError("Timed out waiting to release MemoryS3 read")
        try:
            body, etag = self.objects[Key]
        except KeyError as exc:
            raise self._missing("GetObject") from exc
        return {"Body": io.BytesIO(body), "ETag": f'"{etag}"'}

    def head_object(self, *, Bucket: str, Key: str):
        del Bucket
        try:
            _, etag = self.objects[Key]
        except KeyError as exc:
            raise self._missing("HeadObject") from exc
        return {"ETag": f'"{etag}"'}

    @staticmethod
    def _missing(operation: str) -> ClientError:
        return ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            operation,
        )


def _release_geojson(dc_key: str, date_value: str) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [-75.1, 39.9]},
                    "properties": {
                        "dc_key": dc_key,
                        "race": "B",
                        "sex": "M",
                        "fatal": False,
                        "date": date_value,
                        "age_group": "18 to 30",
                        "has_court_case": None,
                        "age": 25.0,
                        "street_name": None,
                        "block_number": None,
                        "zip_code": None,
                        "council_district": None,
                        "police_district": None,
                        "neighborhood": None,
                        "school_name": None,
                        "house_district": None,
                        "senate_district": None,
                        "segment_id": None,
                    },
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _release_id(label: str) -> str:
    """Return a realistic content-addressed release directory for a test label."""
    return hashlib.sha256(label.encode()).hexdigest()


def _publish_shootings_release(
    s3: MemoryS3,
    *,
    release_id: str,
    dc_key: str,
    data_through: str,
    event_date: str | None = None,
) -> None:
    release_digest = _release_id(release_id)
    previous_application = None
    existing_pointer = s3.objects.get(data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY)
    if existing_pointer is not None:
        existing_manifest = json.loads(existing_pointer[0])
        previous_application = existing_manifest.get("application_data")
    data_body = _release_geojson(dc_key, f"{event_date or data_through} 00:00:00")
    metadata_body = json.dumps(
        {"data_through": data_through, "last_updated": f"{data_through}T12:00:00Z"},
        separators=(",", ":"),
    ).encode()
    data_key = f"processed/shootings/releases/{release_digest}/shootings.geojson"
    metadata_key = f"processed/shootings/releases/{release_digest}/meta.json"
    s3.put(data_key, data_body, f"data-{release_id}")
    s3.put(metadata_key, metadata_body, f"meta-{release_id}")
    manifest = {
        "schema_version": 2,
        "version": f"sha256:{release_digest}",
        "published_at": f"{data_through}T12:00:00Z",
        "downloads": [],
        "application_data": {
            "schema_version": 1,
            "data": {
                "key": data_key,
                "sha256": hashlib.sha256(data_body).hexdigest(),
            },
            "metadata": {
                "key": metadata_key,
                "sha256": hashlib.sha256(metadata_body).hexdigest(),
            },
        },
        **(
            {"previous_application_data": previous_application}
            if previous_application is not None
            else {}
        ),
    }
    s3.put(
        data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY,
        json.dumps(manifest, separators=(",", ":")).encode(),
        f"pointer-{release_id}",
    )


def _publish_homicides_release(s3: MemoryS3, *, release_label: str) -> str:
    """Publish one valid content-addressed homicide release for API tests."""
    release_digest = _release_id(release_label)
    totals_body = json.dumps(
        {"2026": {"annual": 10, "ytd": 8}},
        separators=(",", ":"),
    ).encode()
    metadata_body = json.dumps(
        {"data_through": "2026-08-17", "last_updated": "2026-08-17T12:00:00Z"},
        separators=(",", ":"),
    ).encode()
    totals_key = f"processed/homicides/releases/{release_digest}/homicide_totals.json"
    metadata_key = f"processed/homicides/releases/{release_digest}/meta.json"
    s3.put(totals_key, totals_body, f"totals-{release_label}")
    s3.put(metadata_key, metadata_body, f"meta-{release_label}")
    pointer = {
        "schema_version": 1,
        "version": f"sha256:{release_digest}",
        "totals": {
            "key": totals_key,
            "sha256": hashlib.sha256(totals_body).hexdigest(),
        },
        "metadata": {
            "key": metadata_key,
            "sha256": hashlib.sha256(metadata_body).hexdigest(),
        },
    }
    s3.put(
        "processed/homicides/release.json",
        json.dumps(pointer, separators=(",", ":")).encode(),
        f"homicides-pointer-{release_label}",
    )
    return release_digest


def _boundary_body(dataset: str, label: str) -> bytes:
    join_field = BOUNDARY_JOIN_FIELDS[dataset]
    properties = {"label": label}
    if join_field is not None:
        properties[join_field] = label
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[-75.2, 39.9], [-75.1, 39.9], [-75.1, 40.0], [-75.2, 39.9]]
                        ],
                    },
                    "properties": properties,
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def _publish_boundary_release(s3: MemoryS3, labels: dict[str, str]) -> str:
    complete_labels = {
        dataset: labels.get(dataset, f"default-{dataset}") for dataset in BOUNDARY_JOIN_FIELDS
    }
    bodies = {dataset: _boundary_body(dataset, label) for dataset, label in complete_labels.items()}
    checksums = {dataset: hashlib.sha256(body).hexdigest() for dataset, body in bodies.items()}
    release_id = compute_boundary_release_id(checksums)
    entries = {}
    for dataset, body in sorted(bodies.items()):
        key = boundary_release_key("reference", release_id, dataset)
        s3.put(key, body, f"member-{release_id}-{dataset}")
        entries[dataset] = {"key": key, "sha256": checksums[dataset]}
    pointer = {
        "schema_version": 1,
        "version": f"sha256:{release_id}",
        "datasets": entries,
    }
    s3.put(
        "reference/boundaries_release.json",
        json.dumps(pointer, separators=(",", ":")).encode(),
        f"boundaries-pointer-{release_id}",
    )
    return release_id


def _boundary_label(snapshot: AppDataSnapshot, dataset: str) -> str:
    boundaries = data_loader.require_boundaries(snapshot)
    return str(boundaries.datasets[dataset]["features"][0]["properties"]["label"])


def test_boundary_member_failure_keeps_the_complete_previous_generation() -> None:
    s3 = MemoryS3()
    _publish_boundary_release(s3, {"city_limits": "old-city", "neighborhoods": "old-hood"})
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_boundary_data(app)
    installed = data_loader.get_data_snapshot(app).boundaries

    release_id = _publish_boundary_release(
        s3,
        {"city_limits": "new-city", "neighborhoods": "new-hood"},
    )
    bad_key = boundary_release_key("reference", release_id, "neighborhoods")
    _, etag = s3.objects[bad_key]
    s3.put(bad_key, _boundary_body("neighborhoods", "corrupt"), etag)

    with pytest.raises(ValueError, match="checksum mismatch"):
        data_loader.load_boundary_data(app)

    assert data_loader.get_data_snapshot(app).boundaries is installed
    assert _boundary_label(data_loader.get_data_snapshot(app), "city_limits") == "old-city"
    assert _boundary_label(data_loader.get_data_snapshot(app), "neighborhoods") == "old-hood"


def test_boundary_refresh_detects_changed_bytes_with_the_same_dataset_names(
    monkeypatch,
) -> None:
    s3 = MemoryS3()
    first_release = _publish_boundary_release(s3, {"city_limits": "one"})
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_boundary_data(app)

    second_release = _publish_boundary_release(s3, {"city_limits": "two"})
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 0)
    data_loader.refresh_if_stale(app, ["boundaries_manifest"])

    assert second_release != first_release
    assert _boundary_label(data_loader.get_data_snapshot(app), "city_limits") == "two"


def test_boundary_generation_builds_off_state_before_one_whole_swap() -> None:
    s3 = MemoryS3()
    _publish_boundary_release(s3, {"city_limits": "old-city", "neighborhoods": "old-hood"})
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_boundary_data(app)
    installed = data_loader.get_data_snapshot(app).boundaries

    release_id = _publish_boundary_release(
        s3,
        {"city_limits": "new-city", "neighborhoods": "new-hood"},
    )
    blocked_key = boundary_release_key("reference", release_id, "neighborhoods")
    member_started = Event()
    allow_member = Event()
    s3.block_key = blocked_key
    s3.get_started = member_started
    s3.allow_get = allow_member
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(data_loader.load_boundary_data, app)
        assert member_started.wait(timeout=2)
        assert app.state.data_snapshot.boundaries is installed
        assert _boundary_label(app.state.data_snapshot, "city_limits") == "old-city"
        assert _boundary_label(app.state.data_snapshot, "neighborhoods") == "old-hood"
        allow_member.set()
        future.result(timeout=2)

    assert _boundary_label(app.state.data_snapshot, "city_limits") == "new-city"
    assert _boundary_label(app.state.data_snapshot, "neighborhoods") == "new-hood"


def test_boundary_pointer_rejects_wrong_release_key_before_member_reads() -> None:
    s3 = MemoryS3()
    _publish_boundary_release(s3, {"city_limits": "trusted"})
    pointer_key = "reference/boundaries_release.json"
    pointer_body, pointer_etag = s3.objects[pointer_key]
    pointer = json.loads(pointer_body)
    pointer["datasets"]["city_limits"]["key"] = "reference/city_limits.geojson"
    s3.put(pointer_key, json.dumps(pointer).encode(), pointer_etag)
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    s3.get_calls.clear()

    with pytest.raises(ValueError, match="exact release key"):
        data_loader.load_boundary_data(app)

    assert s3.get_calls == [pointer_key]


def test_boundary_rollout_accepts_legacy_once_but_never_downgrades(monkeypatch) -> None:
    s3 = MemoryS3()
    release_pointer_key = "reference/boundaries_release.json"
    legacy_pointer_key = "reference/boundaries_manifest.json"
    legacy_pointer = json.dumps(
        {"datasets": {dataset: f"{dataset}.geojson" for dataset in BOUNDARY_JOIN_FIELDS}},
        separators=(",", ":"),
    ).encode()
    s3.put(legacy_pointer_key, legacy_pointer, "legacy-pointer")
    monkeypatch.setattr(
        data_loader,
        "read_reference_json",
        lambda name, s3: json.loads(_boundary_body(name.removesuffix(".geojson"), "legacy")),
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3

    data_loader.load_boundary_data(app)
    assert data_loader.require_boundaries(app.state.data_snapshot).source_kind == "legacy"

    _publish_boundary_release(s3, {"city_limits": "release"})
    data_loader.load_boundary_data(app)
    assert data_loader.require_boundaries(app.state.data_snapshot).source_kind == "release"

    del s3.objects[release_pointer_key]
    s3.put(legacy_pointer_key, legacy_pointer, "legacy-downgrade")
    with pytest.raises(RuntimeError, match="legacy manifest"):
        data_loader.load_boundary_data(app)

    assert _boundary_label(app.state.data_snapshot, "city_limits") == "release"


def test_legacy_boundary_pointer_rejects_cross_dataset_object_keys() -> None:
    s3 = MemoryS3()
    datasets = {dataset: f"{dataset}.geojson" for dataset in BOUNDARY_JOIN_FIELDS}
    datasets["city_limits"] = "../private.json"
    s3.put(
        "reference/boundaries_manifest.json",
        json.dumps({"datasets": datasets}, separators=(",", ":")).encode(),
        "legacy-invalid",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3

    with pytest.raises(ValueError, match="city_limits.*invalid key"):
        data_loader.load_boundary_data(app)


def test_valid_homicides_release_reads_only_the_exact_pointer_objects() -> None:
    s3 = MemoryS3()
    release_digest = _publish_homicides_release(s3, release_label="valid")
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3

    data_loader.load_homicides_data(app)

    homicides = data_loader.require_homicides(data_loader.get_data_snapshot(app))
    assert homicides.totals["2026"] == {"annual": 10, "ytd": 8}
    assert s3.get_calls == [
        "processed/homicides/release.json",
        f"processed/homicides/releases/{release_digest}/homicide_totals.json",
        f"processed/homicides/releases/{release_digest}/meta.json",
    ]


def _street_body(segment_id: object = "123") -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-75.2, 39.9], [-75.1, 40.0]],
                    },
                    "properties": {"segment_id": segment_id},
                }
            ],
        },
        separators=(",", ":"),
    ).encode()


def test_streets_body_and_source_token_come_from_one_s3_read() -> None:
    s3 = MemoryS3()
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    streets_key = app.state.dataset_keys["streets"]
    s3.put(streets_key, _street_body(" 123 "), "streets-v1")

    data_loader.load_streets_data(app)

    streets = data_loader.require_streets(data_loader.get_data_snapshot(app))
    assert streets.source_token == ("legacy", "streets-v1")
    assert set(streets.by_segment_id) == {"123"}
    assert s3.get_calls == [streets_key]


@pytest.mark.parametrize("segment_id", [None, "", "   ", 123, True])
def test_streets_reject_every_missing_or_coercive_segment_id(segment_id: object) -> None:
    s3 = MemoryS3()
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    s3.put(app.state.dataset_keys["streets"], _street_body(segment_id), "streets-invalid")

    with pytest.raises(ValueError, match="blank or invalid segment_id"):
        data_loader.load_streets_data(app)


@pytest.mark.parametrize(
    "invalid_case",
    [
        "mixed_release",
        "malformed_prefix",
        "wrong_filename",
        "mismatched_manifest_version",
        "malformed_manifest_version",
    ],
)
def test_shootings_pointer_rejects_untrusted_release_keys_before_object_reads(
    invalid_case: str,
) -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="trusted",
        dc_key="trusted-victim",
        data_through="2026-08-17",
    )
    pointer_body, pointer_etag = s3.objects[data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]
    pointer = json.loads(pointer_body)
    release_digest = _release_id("trusted")
    other_digest = _release_id("other")
    if invalid_case == "mixed_release":
        pointer["application_data"]["metadata"]["key"] = (
            f"processed/shootings/releases/{other_digest}/meta.json"
        )
    elif invalid_case == "malformed_prefix":
        pointer["application_data"]["data"]["key"] = (
            f"untrusted/shootings/releases/{release_digest}/shootings.geojson"
        )
    elif invalid_case == "wrong_filename":
        pointer["application_data"]["data"]["key"] = (
            f"processed/shootings/releases/{release_digest}/not-shootings.geojson"
        )
    elif invalid_case == "mismatched_manifest_version":
        pointer["version"] = f"sha256:{other_digest}"
    else:
        pointer["version"] = f"sha256:{release_digest.upper()}"
    s3.put(
        data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY,
        json.dumps(pointer, separators=(",", ":")).encode(),
        pointer_etag,
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    s3.get_calls.clear()

    with pytest.raises(ValueError, match="release|manifest"):
        data_loader.load_shootings_data(app)

    assert s3.get_calls == [data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]


def test_previous_shootings_pointer_is_validated_before_current_object_reads() -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="previous",
        dc_key="previous-victim",
        data_through="2026-08-16",
    )
    _publish_shootings_release(
        s3,
        release_id="current",
        dc_key="current-victim",
        data_through="2026-08-17",
    )
    pointer_body, pointer_etag = s3.objects[data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]
    pointer = json.loads(pointer_body)
    pointer["previous_application_data"]["data"]["key"] = (
        f"processed/shootings/releases/{_release_id('previous')}/unexpected.json"
    )
    s3.put(
        data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY,
        json.dumps(pointer, separators=(",", ":")).encode(),
        pointer_etag,
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    s3.get_calls.clear()

    with pytest.raises(ValueError, match="exact release filename"):
        data_loader.load_shootings_data(app)

    assert s3.get_calls == [data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]


@pytest.mark.parametrize(
    "invalid_case",
    [
        "mixed_release",
        "malformed_prefix",
        "wrong_filename",
        "mismatched_pointer_version",
        "malformed_pointer_version",
    ],
)
def test_homicides_pointer_rejects_untrusted_release_keys_before_object_reads(
    invalid_case: str,
) -> None:
    s3 = MemoryS3()
    release_digest = _publish_homicides_release(s3, release_label="trusted")
    pointer_key = "processed/homicides/release.json"
    pointer_body, pointer_etag = s3.objects[pointer_key]
    pointer = json.loads(pointer_body)
    other_digest = _release_id("other")
    if invalid_case == "mixed_release":
        pointer["metadata"]["key"] = f"processed/homicides/releases/{other_digest}/meta.json"
    elif invalid_case == "malformed_prefix":
        pointer["totals"]["key"] = (
            f"untrusted/homicides/releases/{release_digest}/homicide_totals.json"
        )
    elif invalid_case == "wrong_filename":
        pointer["totals"]["key"] = f"processed/homicides/releases/{release_digest}/totals.json"
    elif invalid_case == "mismatched_pointer_version":
        pointer["version"] = f"sha256:{other_digest}"
    else:
        pointer["version"] = f"sha256:{release_digest.upper()}"
    s3.put(
        pointer_key,
        json.dumps(pointer, separators=(",", ":")).encode(),
        pointer_etag,
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    s3.get_calls.clear()

    with pytest.raises(ValueError, match="release|pointer"):
        data_loader.load_homicides_data(app)

    assert s3.get_calls == [pointer_key]


def _version(version: str, victim: str) -> ShootingVersionSnapshot:
    row = {"dc_key": victim, "date": "2026-01-01 00:00:00", "year": 2026}
    return ShootingVersionSnapshot(
        version=version,
        years=(2026,),
        rows_by_year={2026: (row,)},
        meta={
            "version": version,
            "generated_at": "2026-01-02T00:00:00Z",
            "rows": 1,
            "years": [2026],
            "years_meta": {
                2026: {
                    "rows": 1,
                    "rows_url": f"/shootings/rows/{version}/2026.ndjson",
                }
            },
        },
    )


def _shootings(
    current: ShootingVersionSnapshot,
    previous: ShootingVersionSnapshot | None = None,
) -> ShootingsSnapshot:
    return ShootingsSnapshot(
        current=current,
        previous=previous,
        freshness={"data_through": "2026-01-01"},
        source_kind="release",
        source_token=("release", current.version),
    )


def test_snapshot_json_is_deeply_immutable_and_still_serializable() -> None:
    version = _version("immutable-version", "immutable-victim")

    with pytest.raises(TypeError, match="immutable"):
        version.meta["generated_at"] = "changed"
    with pytest.raises(TypeError, match="immutable"):
        version.rows_by_year[2026][0]["dc_key"] = "changed"

    encoded = json.dumps(version.rows_by_year)
    assert "immutable-victim" in encoded


def _app_with_shootings(shootings: ShootingsSnapshot) -> FastAPI:
    app = FastAPI()
    app.state.data_snapshot = AppDataSnapshot(shootings=shootings)
    app.state.dataset_last_checked = {}
    app.state.dataset_last_failed = {}
    app.state.dataset_refresh_lock = Lock()
    app.state.s3 = MagicMock()
    app.include_router(shootings_router)
    return app


def test_missing_timestamps_never_throttle_the_initial_refresh(monkeypatch) -> None:
    app = _app_with_shootings(_shootings(_version("old-version", "old-victim")))
    reloads: list[str] = []

    # A numeric sentinel such as 0.0 looks recent whenever process uptime is
    # lower than the TTL/backoff. Missing entries must mean "never attempted."
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 10**12)
    monkeypatch.setattr(data_loader.settings, "api_refresh_failure_backoff_seconds", 10**12)
    monkeypatch.setattr(
        data_loader,
        "_current_source_token",
        lambda app, name: ("release", "new-version"),
    )
    monkeypatch.setattr(
        data_loader,
        "_reload_dataset",
        lambda app, name: reloads.append(name),
    )

    data_loader.refresh_if_stale(app, ["shootings"])

    assert reloads == ["shootings"]
    assert "shootings" in app.state.dataset_last_checked
    assert "shootings" not in app.state.dataset_last_failed


def test_concurrent_refresh_builds_once_and_swaps_only_when_complete(monkeypatch) -> None:
    old = _shootings(_version("old-version", "old-victim"))
    app = _app_with_shootings(old)
    build_started = Event()
    allow_swap = Event()
    reloads = 0

    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 60)
    monkeypatch.setattr(
        data_loader,
        "_current_source_token",
        lambda app, name: ("release", "new-version"),
    )

    def delayed_reload(target: FastAPI, name: str) -> None:
        nonlocal reloads
        reloads += 1
        build_started.set()
        assert allow_swap.wait(timeout=2)
        new = _shootings(_version("new-version", "new-victim"), previous=old.current)
        target.state.data_snapshot = AppDataSnapshot(shootings=new)

    monkeypatch.setattr(data_loader, "_reload_dataset", delayed_reload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(data_loader.refresh_if_stale, app, ["shootings"])
        assert build_started.wait(timeout=2)
        second = executor.submit(data_loader.refresh_if_stale, app, ["shootings"])

        # The only published pointer remains the complete old snapshot while
        # the candidate is still being constructed. A concurrent request does
        # not wait for S3; it immediately continues with that old snapshot.
        second.result(timeout=0.5)
        assert app.state.data_snapshot is not None
        assert app.state.data_snapshot.shootings.current.version == "old-version"
        allow_swap.set()
        first.result(timeout=2)

    assert reloads == 1
    assert app.state.data_snapshot.shootings.current.version == "new-version"


def test_refresh_failure_serves_stale_and_uses_short_failure_backoff(monkeypatch) -> None:
    old = _shootings(_version("old-version", "old-victim"))
    app = _app_with_shootings(old)
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 0)
    monkeypatch.setattr(data_loader.settings, "api_refresh_failure_backoff_seconds", 30)
    attempts = 0

    def fail_check(app: FastAPI, name: str) -> tuple[str, ...]:
        nonlocal attempts
        attempts += 1
        raise TimeoutError("S3 is temporarily unavailable")

    monkeypatch.setattr(data_loader, "_current_source_token", fail_check)

    data_loader.refresh_if_stale(app, ["shootings"])
    data_loader.refresh_if_stale(app, ["shootings"])

    assert app.state.data_snapshot.shootings is old
    assert "shootings" not in app.state.dataset_last_checked
    assert "shootings" in app.state.dataset_last_failed
    assert attempts == 1


def test_previous_shootings_version_remains_byte_stable_during_rollover(monkeypatch) -> None:
    old = _version("old-version", "old-victim")
    app = _app_with_shootings(_shootings(_version("new-version", "new-victim"), old))
    # Prevent the route dependency from making an S3 check in this isolated app.
    app.state.dataset_last_checked["shootings"] = time.monotonic()
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 60)

    with TestClient(app) as client:
        old_response = client.get("/shootings/rows/old-version/2026.ndjson")
        new_response = client.get("/shootings/rows/new-version/2026.ndjson")

    assert old_response.status_code == 200
    assert old_response.json()["dc_key"] == "old-victim"
    assert old_response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert new_response.json()["dc_key"] == "new-victim"


def test_invalid_candidate_does_not_replace_current_snapshot(monkeypatch) -> None:
    old = _shootings(_version("old-version", "old-victim"))
    app = _app_with_shootings(old)
    monkeypatch.setattr(
        data_loader,
        "_build_shootings_snapshot",
        lambda app: (_ for _ in ()).throw(ValueError("invalid candidate")),
    )

    try:
        data_loader.load_shootings_data(app)
    except ValueError as exc:
        assert str(exc) == "invalid candidate"
    else:
        raise AssertionError("invalid candidate should fail")

    assert app.state.data_snapshot.shootings is old


def test_release_pointer_refreshes_data_and_retains_only_n_minus_one(monkeypatch) -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="one",
        dc_key="victim-one",
        data_through="2026-08-15",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_shootings_data(app)
    first = data_loader.require_shootings(data_loader.get_data_snapshot(app)).current

    _publish_shootings_release(
        s3,
        release_id="two",
        dc_key="victim-two",
        data_through="2026-08-16",
    )
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 0)
    data_loader.refresh_if_stale(app, ["shootings"])
    second_snapshot = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    assert second_snapshot.current.version != first.version
    assert second_snapshot.previous is not None
    assert second_snapshot.previous.version == first.version

    _publish_shootings_release(
        s3,
        release_id="three",
        dc_key="victim-three",
        data_through="2026-08-17",
    )
    data_loader.refresh_if_stale(app, ["shootings"])
    third_snapshot = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    assert third_snapshot.previous is not None
    assert third_snapshot.previous.version == second_snapshot.current.version
    assert third_snapshot.find_version(first.version) is None


def test_release_rollover_reuses_loaded_version_objects_without_refetching() -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="reuse-one",
        dc_key="victim-one",
        data_through="2026-08-15",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_shootings_data(app)
    first_snapshot = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    _publish_shootings_release(
        s3,
        release_id="reuse-two",
        dc_key="victim-two",
        data_through="2026-08-16",
    )
    s3.get_calls.clear()
    data_loader.load_shootings_data(app)
    second_snapshot = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    assert second_snapshot.previous is first_snapshot.current
    assert s3.get_calls == [
        data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY,
        f"processed/shootings/releases/{_release_id('reuse-two')}/shootings.geojson",
        f"processed/shootings/releases/{_release_id('reuse-two')}/meta.json",
    ]

    # A rollback swaps the two immutable pointers. Both versions are already
    # validated, so neither release object should be fetched or rebuilt.
    pointer_body, _ = s3.objects[data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]
    pointer = json.loads(pointer_body)
    pointer["application_data"], pointer["previous_application_data"] = (
        pointer["previous_application_data"],
        pointer["application_data"],
    )
    pointer["version"] = f"sha256:{_release_id('reuse-one')}"
    s3.put(
        data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY,
        json.dumps(pointer, separators=(",", ":")).encode(),
        "pointer-rollback",
    )
    s3.get_calls.clear()
    data_loader.load_shootings_data(app)
    rollback_snapshot = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    assert rollback_snapshot.current is first_snapshot.current
    assert rollback_snapshot.previous is second_snapshot.current
    assert s3.get_calls == [data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]


def test_failed_new_release_keeps_loaded_versions_by_identity() -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="safe-one",
        dc_key="victim-one",
        data_through="2026-08-15",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_shootings_data(app)
    installed = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    _publish_shootings_release(
        s3,
        release_id="safe-two",
        dc_key="victim-two",
        data_through="2026-08-16",
    )
    new_data_key = f"processed/shootings/releases/{_release_id('safe-two')}/shootings.geojson"
    _, etag = s3.objects[new_data_key]
    s3.put(new_data_key, b'{"type":"FeatureCollection","features":[]}', etag)
    s3.get_calls.clear()

    with pytest.raises(ValueError, match="checksum mismatch"):
        data_loader.load_shootings_data(app)

    assert data_loader.require_shootings(data_loader.get_data_snapshot(app)) is installed
    assert s3.get_calls == [data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY, new_data_key]


def test_release_pointer_observes_metadata_only_change(monkeypatch) -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="metadata-one",
        dc_key="same-victim",
        data_through="2026-08-15",
        event_date="2026-08-01",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_shootings_data(app)
    before = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    _publish_shootings_release(
        s3,
        release_id="metadata-two",
        dc_key="same-victim",
        data_through="2026-08-16",
        event_date="2026-08-01",
    )
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 0)
    data_loader.refresh_if_stale(app, ["shootings"])
    after = data_loader.require_shootings(data_loader.get_data_snapshot(app))

    assert after.current.version == before.current.version
    assert after.freshness["data_through"] == "2026-08-16"
    assert after.previous is None


def test_n_minus_one_survives_api_restart() -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="before-restart",
        dc_key="old-victim",
        data_through="2026-08-16",
    )
    old_data = json.loads(s3.objects[data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY][0])[
        "application_data"
    ]
    old_body = json.loads(s3.objects[old_data["data"]["key"]][0])
    old_version = data_loader._compute_version_hash(old_body)
    _publish_shootings_release(
        s3,
        release_id="after-restart",
        dc_key="new-victim",
        data_through="2026-08-17",
    )

    restarted = FastAPI()
    data_loader.init_dataset_keys(restarted)
    restarted.state.s3 = s3
    data_loader.load_shootings_data(restarted)
    loaded = data_loader.require_shootings(data_loader.get_data_snapshot(restarted))

    assert loaded.previous is not None
    assert loaded.previous.version == old_version
    assert loaded.previous.rows_by_year[2026][0]["dc_key"] == "old-victim"


def test_published_pointer_disappearance_never_falls_back_to_mutable_mirror(
    monkeypatch,
) -> None:
    s3 = MemoryS3()
    _publish_shootings_release(
        s3,
        release_id="active",
        dc_key="published-victim",
        data_through="2026-08-17",
    )
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = s3
    data_loader.load_shootings_data(app)
    published = data_loader.get_data_snapshot(app)
    del s3.objects[data_loader.PUBLIC_DOWNLOAD_MANIFEST_KEY]
    monkeypatch.setattr(data_loader.settings, "api_refresh_ttl_seconds", 0)

    data_loader.refresh_if_stale(app, ["shootings"])

    assert data_loader.get_data_snapshot(app) is published
    assert "shootings" not in app.state.dataset_last_checked


def test_legacy_rollout_source_is_fetched_once(monkeypatch) -> None:
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = MemoryS3()
    calls = 0
    geojson = json.loads(_release_geojson("legacy-victim", "2026-08-17 00:00:00"))

    monkeypatch.setattr(
        data_loader,
        "_shootings_pointer",
        lambda s3: (None, None, "pointer-etag"),
    )

    def legacy_source(app: FastAPI, pointer_etag: str | None):
        nonlocal calls
        calls += 1
        assert pointer_etag == "pointer-etag"
        return (
            geojson,
            {"data_through": "2026-08-17"},
            ("legacy", "pointer-etag", "data-etag", "meta-etag"),
        )

    monkeypatch.setattr(data_loader, "_legacy_shootings_source", legacy_source)

    candidate = data_loader._build_shootings_snapshot(app)

    assert calls == 1
    assert candidate.source_kind == "legacy"


def test_release_marked_legacy_metadata_requires_the_pointer(monkeypatch) -> None:
    app = FastAPI()
    data_loader.init_dataset_keys(app)
    app.state.s3 = MemoryS3()
    monkeypatch.setattr(
        data_loader,
        "read_processed_geojson_json",
        lambda name, s3: json.loads(_release_geojson("marked-victim", "2026-08-17 00:00:00")),
    )
    monkeypatch.setattr(
        data_loader,
        "read_processed_json",
        lambda name, s3: {
            "data_through": "2026-08-17",
            "release_pointer_schema_version": 1,
        },
    )

    try:
        data_loader._legacy_shootings_source(app, None)
    except RuntimeError as exc:
        assert "release pointer is required" in str(exc)
    else:
        raise AssertionError("release-marked mirrors must not become authoritative")
