"""API against the real data/grid.duckdb (skipped if it hasn't been built)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import DB_PATH, app

pytestmark = pytest.mark.skipif(not Path(DB_PATH).exists(), reason="run pipeline.run first")
client = TestClient(app)


def test_meta():
    m = client.get("/meta").json()
    assert m["licence_areas"] == ["EPN", "LPN", "SPN"]
    assert sum(w["weight"] for w in m["weights"]) == 100
    assert "published headroom" in m["disclaimer"].lower()


def test_sites_geojson_and_filters():
    all_ = client.get("/sites").json()
    assert all_["type"] == "FeatureCollection" and all_["count"] > 900
    lpn = client.get("/sites", params={"licence_area": "LPN"}).json()
    assert 0 < lpn["count"] < all_["count"]
    assert {f["properties"]["licence_area"] for f in lpn["features"]} == {"LPN"}
    hi = client.get("/sites", params={"min_score": 80, "voltage": [11, 6.6]}).json()
    assert all(f["properties"]["score"] >= 80 for f in hi["features"])
    assert {f["properties"]["voltage"] for f in hi["features"]} <= {11.0, 6.6}


def test_site_detail_every_number_has_a_source():
    top = max(client.get("/sites").json()["features"], key=lambda f: f["properties"]["score"] or -1)
    d = client.get(f"/sites/{top['properties']['site_id']}").json()
    assert d["rank"] == 1
    assert len(d["signals"]) == 5
    for sig in d["signals"]:
        assert sig["source"]["dataset_id"] and sig["source"]["publish_date"], sig
    assert d["capacity"]["source"]["dataset_id"]
    assert d["headroom_2030"]["source"]["dataset_id"]
    assert sum(v["default"] for v in d["headroom_2030"]["values"]) == 1


def test_unknown_site_404():
    assert client.get("/sites/NOPE").status_code == 404
