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
    s1 = pd.DataFrame({"site_id": ["A"], **base, "snapshot_date": ["2026-11-17"]})
    s2 = pd.DataFrame({"site_id": ["A"], **{**base, "queue_mw": [14.0]}, "snapshot_date": ["2026-12-01"]})
    b = pd.DataFrame(columns=["bsp_id", "name", "queue_mw", "headroom_mw", "stuck_mw", "snapshot_date"])
    ch = medallion.changes(pd.concat([s1, s2]), b)
    assert ch[["id", "measure", "previous", "latest", "change"]].values.tolist() == [["A", "queue_mw", 10.0, 14.0, 4.0]]
    assert medallion.changes(s1, b).empty  # one snapshot: nothing to compare


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
    d = _load()
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
