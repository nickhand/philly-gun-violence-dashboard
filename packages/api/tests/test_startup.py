"""Startup and endpoint tests using a mocked S3 TestClient.

The `client` fixture is defined in conftest.py. It runs the full lifespan
(startup loads all datasets) with mocked S3 calls, so these tests exercise
the real startup and request-handling paths — they catch import errors,
AttributeErrors on settings fields, broken route registrations, and bad
state access in handlers.
"""

from dataclasses import replace

import pytest


class TestImports:
    """Verify the app module tree imports without errors."""

    def test_import_main(self):
        import app.main  # noqa: F401

    def test_import_data_loader(self):
        import app.data_loader  # noqa: F401

    def test_import_config(self):
        import app.config  # noqa: F401

    def test_import_routers(self):
        import app.routers.boundaries  # noqa: F401
        import app.routers.health  # noqa: F401
        import app.routers.homicides  # noqa: F401
        import app.routers.meta  # noqa: F401
        import app.routers.shootings  # noqa: F401
        import app.routers.stats  # noqa: F401
        import app.routers.streets  # noqa: F401
        import app.stats_page  # noqa: F401


class TestOpenAPI:
    """Verify the machine-readable API description matches the public contract."""

    def test_project_metadata_and_external_docs(self):
        from app.main import app

        schema = app.openapi()
        info = schema["info"]

        assert info["title"] == "Philadelphia Gun Violence Dashboard API"
        assert info["summary"].startswith("Read-only application service")
        assert "not a supported public download interface" in info["description"]
        assert "one row represents one victim" in info["description"]
        assert "homicide totals are a separate citywide measure" in info["description"]
        assert "preliminary" in info["description"]
        assert "license" not in info
        assert info["contact"]["url"].endswith("/about#corrections")
        assert schema["externalDocs"] == {
            "description": "Data access, fields, sources, and terms",
            "url": "https://www.nickhand.dev/philly-gun-violence-map/data",
        }

    def test_configured_canary_origin_is_exact_and_null_origin_is_rejected(self, monkeypatch):
        from app import main

        monkeypatch.setattr(
            main.settings,
            "api_cors_origins",
            "https://dashboard-canary.example.com",
        )
        assert "https://dashboard-canary.example.com" in main._cors_origins()
        assert "null" not in main._cors_origins()

    def test_shooting_download_contracts(self):
        from app.main import app

        schema = app.openapi()
        manifest = schema["paths"]["/shootings/meta"]["get"]
        rows = schema["paths"]["/shootings/rows/{version}/{year}.ndjson"]["get"]

        assert manifest["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ShootingsManifest"
        }
        assert "years_meta" in schema["components"]["schemas"]["ShootingsManifest"]["properties"]
        assert set(rows["responses"]["200"]["content"]) == {"application/x-ndjson"}
        ndjson_schema = rows["responses"]["200"]["content"]["application/x-ndjson"]["schema"]
        assert ndjson_schema["type"] == "string"
        assert "one shooting victim" in ndjson_schema["description"]


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_readiness_exposes_loaded_snapshot_freshness(self, client, monkeypatch):
        from app.routers import health

        monkeypatch.setattr(health.settings, "api_readiness_max_data_age_days", 10_000)
        resp = client.get("/ready")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ready"
        assert body["datasets"]["shootings"] == {
            "data_through": "2023-01-15",
            "age_days": body["datasets"]["shootings"]["age_days"],
            "source": "legacy",
            "current": True,
        }
        assert body["datasets"]["homicides"]["source"] == "legacy"
        assert body["datasets"]["boundaries"] == {
            "source": "release",
            "current": True,
        }
        assert body["datasets"]["streets"] == {
            "source": "legacy",
            "current": True,
        }

    def test_readiness_fails_when_loaded_data_is_too_old(self, client, monkeypatch):
        from app.routers import health

        monkeypatch.setattr(health.settings, "api_readiness_max_data_age_days", 1)
        resp = client.get("/ready")

        assert resp.status_code == 503
        assert resp.json()["status"] == "stale"

    def test_readiness_reports_a_failed_upstream_refresh(self, client, monkeypatch):
        import time

        from app.routers import health

        monkeypatch.setattr(health.settings, "api_readiness_max_data_age_days", 10_000)
        client.app.state.dataset_last_failed["shootings"] = time.monotonic()

        resp = client.get("/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["refresh_failures"] == ["shootings"]

    def test_readiness_clears_a_failure_after_a_successful_recheck(self, client, monkeypatch):
        from app.routers import health

        monkeypatch.setattr(health.settings, "api_readiness_max_data_age_days", 10_000)
        client.app.state.dataset_last_failed = {"shootings": 0.0}
        client.app.state.dataset_last_checked["shootings"] = 0.0

        resp = client.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["refresh_failures"] == []


class TestShootings:
    def test_meta_200(self, client):
        resp = client.get("/shootings/meta")
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "max-age=0, must-revalidate"
        assert resp.headers["etag"]

    def test_meta_has_version_and_years(self, client):
        body = client.get("/shootings/meta").json()
        assert "version" in body
        assert "years" in body
        assert 2023 in body["years"]

    def test_rows_ndjson_200(self, client):
        meta = client.get("/shootings/meta").json()
        version = meta["version"]
        resp = client.get(f"/shootings/rows/{version}/2023.ndjson")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
        assert resp.headers["x-robots-tag"] == "noindex"

    def test_meta_304_preserves_cache_validators(self, client):
        first = client.get("/shootings/meta")
        second = client.get(
            "/shootings/meta",
            headers={"If-None-Match": first.headers["etag"]},
        )

        assert second.status_code == 304
        assert second.headers["etag"] == first.headers["etag"]
        assert second.headers["cache-control"] == "max-age=0, must-revalidate"

    def test_meta_etag_changes_when_generated_at_changes(self, client):
        from app.data_loader import get_data_snapshot, require_shootings

        first = client.get("/shootings/meta")
        snapshot = get_data_snapshot(client.app)
        shootings = require_shootings(snapshot)
        changed_current = replace(
            shootings.current,
            meta={
                **shootings.current.meta,
                "generated_at": "2026-08-17T23:00:00+00:00",
            },
        )
        client.app.state.data_snapshot = replace(
            snapshot,
            shootings=replace(shootings, current=changed_current),
        )
        second = client.get("/shootings/meta")

        assert second.headers["etag"] != first.headers["etag"]
        assert second.json()["version"] == first.json()["version"]

    def test_rows_wrong_version_404(self, client):
        resp = client.get("/shootings/rows/wrongversion/2023.ndjson")
        assert resp.status_code == 404

    def test_rows_missing_year_404(self, client):
        meta = client.get("/shootings/meta").json()
        version = meta["version"]
        resp = client.get(f"/shootings/rows/{version}/1800.ndjson")
        assert resp.status_code == 404


class TestBoundaries:
    def test_list_200(self, client):
        resp = client.get("/boundaries")
        assert resp.status_code == 200

    def test_list_contains_neighborhoods(self, client):
        body = client.get("/boundaries").json()
        assert "neighborhoods" in body["datasets"]

    def test_dataset_200(self, client):
        resp = client.get("/boundaries/neighborhoods")
        assert resp.status_code == 200

    def test_missing_dataset_404(self, client):
        resp = client.get("/boundaries/does_not_exist")
        assert resp.status_code == 404


class TestStreets:
    def test_streets_200(self, client):
        resp = client.get("/streets")
        assert resp.status_code == 200

    @pytest.mark.parametrize("limit", [0, 5001])
    def test_streets_rejects_out_of_range_page_size(self, client, limit):
        resp = client.get("/streets", params={"limit": limit})
        assert resp.status_code == 422

    def test_streets_deduplicates_requested_segment_ids(self, client):
        resp = client.get("/streets", params={"segment_ids": "12345,12345"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_streets_rejects_too_many_unique_segment_ids(self, client):
        segment_ids = ",".join(str(value) for value in range(501))
        resp = client.get("/streets", params={"segment_ids": segment_ids})
        assert resp.status_code == 422


class TestHomicides:
    def test_homicides_200(self, client):
        resp = client.get("/homicides/2023")
        assert resp.status_code == 200

    def test_homicides_missing_year_404(self, client):
        resp = client.get("/homicides/1800")
        assert resp.status_code == 404


class TestMeta:
    def test_meta_200(self, client):
        resp = client.get("/meta")
        assert resp.status_code == 200

    def test_meta_uses_same_loaded_snapshot_as_stats(self, client):
        body = client.get("/meta").json()

        assert body["shootings"]["data_through"] == "2023-01-15"
        assert body["homicides"]["data_through"] == "2023-01-16"


class TestStatsPage:
    def test_stats_page_is_crawler_visible_html(self, client):
        resp = client.get("/stats")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        canonical = (
            '<link rel="canonical" href="https://www.nickhand.dev/philly-gun-violence-map/stats"'
        )
        assert canonical in resp.text
        assert '"@type": "FAQPage"' in resp.text
        assert "No JavaScript required" in resp.text

    def test_stats_page_uses_loaded_counts_and_separate_freshness_dates(self, client):
        resp = client.get("/stats")

        assert '<div class="figure">1</div>' in resp.text
        assert '<span class="c-fatal">0 fatal</span>' in resp.text
        assert '<span class="c-nonfatal">1 nonfatal</span>' in resp.text
        freshness = "Shootings through January 15, 2023 · Homicides through January 16, 2023"
        assert freshness in resp.text
        assert "As of January 15, 2023, there have been 1 shooting victims" in resp.text
        assert "As of January 16, 2023, Philadelphia has recorded 450 homicides" in resp.text

    def test_stats_page_revalidates_with_etag(self, client):
        first = client.get("/stats")
        etag = first.headers["etag"]

        second = client.get("/stats", headers={"If-None-Match": etag})

        assert first.headers["cache-control"] == "public, max-age=0, must-revalidate"
        assert second.status_code == 304
        assert second.content == b""

    def test_stats_json_matches_the_rendered_html(self, client):
        html_resp = client.get("/stats")
        html = html_resp.text
        resp = client.get(
            "/stats.json",
            headers={"Origin": "http://localhost:3000"},
        )
        stats = resp.json()

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"
        assert resp.headers["x-robots-tag"] == "noindex"
        assert html_resp.headers["x-robots-tag"] == "index, follow"
        assert stats == {
            "shootings_data_through": "2023-01-15",
            "homicides_data_through": "2023-01-16",
            "current_year": 2023,
            "previous_year": 2022,
            "minimum_year": 2023,
            "total_victims_all_years": 1,
            "current_total": 1,
            "current_fatal": 0,
            "current_nonfatal": 1,
            "shootings_previous_ytd": None,
            "shooting_percent_change": None,
            "homicides_ytd": 450,
            "homicides_previous_ytd": None,
            "homicide_percent_change": None,
            "peak": {"year": 2023, "victims": 1, "homicides": 450},
            "years": [{"year": 2023, "victims": 1, "homicides": 450}],
        }
        assert f'<div class="figure">{stats["current_total"]}</div>' in html
        assert f'<span class="c-fatal">{stats["current_fatal"]} fatal</span>' in html
        assert f'<span class="c-nonfatal">{stats["current_nonfatal"]} nonfatal</span>' in html
        assert f'<td class="num">{stats["years"][0]["victims"]}</td>' in html

    def test_stats_json_revalidates_with_etag(self, client):
        first = client.get("/stats.json")
        second = client.get(
            "/stats.json",
            headers={"If-None-Match": first.headers["etag"]},
        )

        assert first.headers["cache-control"] == "public, max-age=0, must-revalidate"
        assert second.status_code == 304
        assert second.content == b""

    def test_dynamic_sitemap(self, client):
        resp = client.get("/sitemap.xml")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert "https://www.nickhand.dev/philly-gun-violence-map/stats" in resp.text
        assert "<lastmod>2023-01-16</lastmod>" in resp.text
