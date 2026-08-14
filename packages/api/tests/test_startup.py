"""Startup and endpoint tests using a mocked S3 TestClient.

The `client` fixture is defined in conftest.py. It runs the full lifespan
(startup loads all datasets) with mocked S3 calls, so these tests exercise
the real startup and request-handling paths — they catch import errors,
AttributeErrors on settings fields, broken route registrations, and bad
state access in handlers.
"""


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


class TestHealth:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestShootings:
    def test_meta_200(self, client):
        resp = client.get("/shootings/meta")
        assert resp.status_code == 200

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

    def test_dynamic_sitemap(self, client):
        resp = client.get("/sitemap.xml")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert "https://www.nickhand.dev/philly-gun-violence-map/stats" in resp.text
        assert "<lastmod>2023-01-16</lastmod>" in resp.text
