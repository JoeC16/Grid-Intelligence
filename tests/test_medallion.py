"""Phase 10: bronze snapshots, silver/gold marts, and the story's numbers."""

from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.main import DB_PATH, _load, app
from pipeline import bronze, medallion

needs_db = pytest.mark.skipif(not Path(DB_PATH).exists(), reason="run pipeline.run first")


# ------------------------------------------------------------------ bronze


def test_snapshots_sorted_and_latest(tmp_path):
    for d in ["2026-11-23", "2026-11-17", "not-a-date"]:
        (tmp_path / "ukpn" / d).mkdir(parents=True)
    assert [p.name for p in bronze.snapshots("UKPN", tmp_path)] == ["2026-11-17", "2026-11-23"]
    assert bronze.latest("UKPN", tmp_path).name == "2026-11-23"
    assert bronze.latest("OTHER", tmp_path) is None


# ------------------------------------------------------------------- marts


def test_runs_out_year_first_negative_from_year():
    h = pd.DataFrame({
        "site_id": ["A"] * 4 + ["B"] * 4 + ["C"] * 2,
        "scenario": ["S"] * 10,
        "year": [2025, 2026, 2030, 2035] * 2 + [2026, 2030],
        "headroom_mw": [-1, 5, -2, -3,   4, 3, 2, 1,   -1, 1],
    })
    out = medallion.runs_out_year(h, "S", 2026)
    assert out["A"] == 2030  # 2025 is before from_year
    assert "B" not in out  # never negative
    assert out["C"] == 2026  # negative now, even if it recovers later


def test_changes_between_snapshots():
    base = {"name": ["X"], "queue_mw": [10.0], "demand_headroom_mw": [5.0], "effective_headroom_mw": [5.0],
            "stuck_mw": [5.0], "score": [50.0]}
    s1 = pd.DataFrame({"site_id": ["A"], "dno": "UKPN", **base, "snapshot_date": ["2026-11-17"]})
    s2 = pd.DataFrame({"site_id": ["A"], "dno": "UKPN", **{**base, "queue_mw": [14.0]}, "snapshot_date": ["2026-12-01"]})
    b = pd.DataFrame(columns=["bsp_id", "dno", "name", "queue_mw", "headroom_mw", "stuck_mw", "snapshot_date"])
    ch = medallion.changes(pd.concat([s1, s2]), b)
    assert ch[["dno", "id", "measure", "previous", "latest", "change"]].values.tolist() == [
        ["UKPN", "A", "queue_mw", 10.0, 14.0, 4.0]]
    assert medallion.changes(s1, b).empty  # one snapshot: nothing to compare


def test_changes_compare_each_dno_with_its_own_previous_snapshot():
    base = {"name": ["X"], "queue_mw": [10.0], "demand_headroom_mw": [5.0], "effective_headroom_mw": [5.0],
            "stuck_mw": [5.0], "score": [50.0]}
    gb = pd.DataFrame({"site_id": ["A"], "dno": "UKPN", **base, "snapshot_date": ["2026-11-17"]})
    es1 = pd.DataFrame({"site_id": ["E"], "dno": "ES", **base, "snapshot_date": ["2026-11-24"]})
    es2 = pd.DataFrame({"site_id": ["E"], "dno": "ES", **{**base, "queue_mw": [12.0]}, "snapshot_date": ["2026-12-24"]})
    b = pd.DataFrame(columns=["bsp_id", "dno", "name", "queue_mw", "headroom_mw", "stuck_mw", "snapshot_date"])
    ch = medallion.changes(pd.concat([gb, es1, es2]), b)
    assert ch[["dno", "id", "change"]].values.tolist() == [["ES", "E", 2.0]]


def test_operator_mart_rolls_up_per_distributor():
    sites = pd.DataFrame({
        "site_id": ["a", "b", "c"], "country": "ES", "dno": "ES", "operator": ["R1-001", "R1-001", "R1-050"],
        "operator_name": ["Big", "Big", "Small"], "licence_area": ["i-DE", "i-DE", "Small distributors"],
        "name": ["S1 20 kV", "S1 132 kV", "S2 20 kV"], "province": ["Castellón", "Castellón", "Teruel"],
        "demand_headroom_mw": [0.0, 10.0, 0.0], "queue_mw": [4.0, 2.0, 1.0], "capacity_taken_mw": [50.0, 5.0, 3.0]})
    scores = pd.DataFrame({"site_id": ["a", "b", "c"], "score": [80.0, 20.0, 60.0], "stuck_mw": [4.0, 0.0, 1.0]})
    m = medallion.operator_mart(sites, scores).set_index("operator")
    assert m.at["R1-001", "sites"] == 2 and m.at["R1-001", "substations"] == 1
    assert m.at["R1-001", "sites_zero_headroom"] == 1 and m.at["R1-001", "share_zero_headroom"] == 0.5
    assert m.at["R1-001", "stuck_mw"] == 4.0 and m.at["R1-001", "top_site_id"] == "a"
    assert m.at["R1-001", "stuck_rank"] == 1 and m.at["R1-050", "stuck_rank"] == 2


@needs_db
def test_gsp_mart_rolls_up_bsps_and_direct_sites():
    d = _load()
    gm, bsps, sites = d["gold_gsp_mart"].set_index("gsp"), d["bsps"], d["sites"]
    g = "NORTHFLEET EAST"
    bsp_stuck = bsps.loc[bsps["gsp"] == g, "stuck_mw"].sum()
    direct = sites[(sites["gsp"] == g) & sites["bsp_id"].isna() & sites["scorable"]]
    direct_stuck = (direct["queue_mw"] - direct["demand_headroom_mw"]).clip(lower=0).sum()
    assert gm.at[g, "stuck_mw"] == pytest.approx(bsp_stuck + direct_stuck)
    assert gm.at[g, "stuck_rank"] == 1


# ------------------------------------------------------------------- story


@needs_db
def test_story_numbers_trace_to_gold():
    st = TestClient(app).get("/story").json()
    ch = {c["id"]: c for c in st["chapters"]}
    from backend.main import _country_data
    d = _country_data(_load(), "GB")
    facts = {f["label"]: f["value"] for f in ch["queue"]["facts"]}
    assert facts["Demand queued"] == pytest.approx(round(d["gold_gsp_mart"]["queue_mw"].sum(), 1), abs=0.05)
    assert facts["Sites with stuck demand"] == int((d["site_scores"]["stuck_mw"] > 0).sum())
    t = d["gold_headroom_timeline"]
    t = t[t["scenario"] == st["scenario"]].set_index("year")
    run = {f["label"]: f["value"] for f in ch["runout"]["facts"]}
    assert run["Primaries below zero, 2030"] == int(t.at[2030, "sites_negative"])
    assert len(ch["runout"]["focus"]["highlight"]) == int(t.at[2030, "sites_negative"])
    ld = d["large_demand"]
    assert {f["label"]: f["value"] for f in ch["bigdemand"]["facts"]}["Large demand projects waiting"] == int(
        (ld["technology"] == "large_demand").sum())


@needs_db
def test_every_chapter_has_sources_and_focus():
    for c in TestClient(app).get("/story").json()["chapters"]:
        assert c["sources"], c["id"]
        assert {"center", "zoom", "view"} <= set(c["focus"]), c["id"]
        assert "available capacity" not in c["body"].lower()


@needs_db
def test_network_geojson():
    n = TestClient(app).get("/network").json()
    kinds = {f["properties"]["kind"] for f in n["features"]}
    assert kinds == {"edge_site", "edge_bsp", "node_bsp", "node_gsp"}


def test_story_wording_names_every_network():
    from backend.story import _who, _whose, _whole_view
    one = [{"name": "UK Power Networks", "map_center": [0.35, 51.55], "map_zoom": 7.6}]
    two = one + [{"name": "SP Energy Networks", "map_center": [-3.5, 54.5], "map_zoom": 7.0}]
    assert _who(one) == "UK Power Networks" and _whose(one) == "UK Power Networks'"
    assert _who(two) == "UK Power Networks and SP Energy Networks" and _whose(two) == "The network operators'"
    assert _whole_view(one) == {"center": [0.35, 51.55], "zoom": 7.6} and _whole_view(two)["zoom"] < 7


@pytest.mark.skipif(not DB_PATH.exists(), reason="needs data/grid.duckdb")
def test_static_export_matches_api(tmp_path):
    import json
    from backend import export_static
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    export_static.export(tmp_path / "public", dist)
    client = TestClient(app)
    for name, path in export_static.endpoints(client).items():
        assert json.loads((tmp_path / "public" / "data" / f"{name}.json").read_text()) == client.get(path).json()
    assert (tmp_path / "public" / "index.html").is_file()



@needs_db
def test_spain_story_numbers_trace_to_data():
    d = _load()
    if "ES" not in set(d["sites"]["country"]):
        pytest.skip("no Spain data")
    st = TestClient(app).get("/story?country=ES").json()
    ch = {c["id"]: c for c in st["chapters"]}
    es = d["sites"][d["sites"]["country"] == "ES"]
    full = {f["label"]: f["value"] for f in ch["es_full"]["facts"]}
    assert full["Busbars published"] == len(es)
    assert full["With zero published headroom"] == int((es["demand_headroom_mw"] <= 0).sum())
    q = {f["label"]: f["value"] for f in ch["es_queue"]["facts"]}
    assert q["Requests waiting (admitted, not evaluated)"] == pytest.approx(round(es["queue_mw"].sum(), 1), abs=0.05)
    ops = TestClient(app).get("/operators?country=ES").json()
    assert ops["count"] == es["operator"].nunique()
    assert ch["es_operators"]["facts"][0]["label"] == ops["operators"][0]["operator_name"]
    assert all(s["dataset_id"].startswith("cnmc-") for c in st["chapters"] for s in c["sources"])


@needs_db
def test_spain_upstream_chapter_traces_to_tree():
    d = _load()
    if "ES" not in set(d["sites"]["country"]):
        pytest.skip("no Spain data")
    ch = {c["id"]: c for c in TestClient(app).get("/story?country=ES").json()["chapters"]}
    facts = {f["label"]: f["value"] for f in ch["es_upstream"]["facts"]}
    es = d["sites"][(d["sites"]["country"] == "ES") & d["sites"]["scorable"]]
    tx = d["bsps"][(d["bsps"]["country"] == "ES") & d["bsps"]["matched"].astype(bool)]
    assert facts["Busbars limited by their transmission node"] == int((es["limiting_level"] == "bsp").sum())
    assert facts["Transmission nodes at zero capacity"] == int((tx["headroom_mw"] <= 0).sum())
    assert ch["es_upstream"]["focus"]["network"] is True
