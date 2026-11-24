"""Data quality checks catch the failures they are meant to (Phase 11)."""

import json

import pandas as pd

from pipeline import checks


def _tables(n=1000):
    sites = pd.DataFrame({
        "site_id": [f"EPN-S{i:06d}" for i in range(n)],
        "lat": [51.5] * n, "lon": [0.1] * n,
        "scorable": [True] * n, "gsp_mapped": [True] * n,
        "demand_headroom_mw": [5.0] * n, "queue_mw": [1.0] * n,
        "bsp_id": [None] * n, "bsp_headroom_mw": [None] * n,
    })
    bsps = pd.DataFrame({"matched": [True] * 10})
    fs = pd.DataFrame({"dataset_id": ["ds"], "publish_date": ["2026-10-19"], "licence": ["CC BY 4.0"]})
    sc = pd.DataFrame({"score": [50.0] * n, "rank": list(range(1, n + 1))})
    return {"sites": sites, "bsps": bsps, "field_sources": fs, "site_scores": sc}


def _failed(t):
    return {c.name for c in checks.check_tables(t) if not c.ok}


def test_clean_tables_pass():
    assert _failed(_tables()) == set()


def test_broken_join_fails():
    t = _tables()
    t["sites"].loc[:50, "site_id"] = [f"UKPN-MRID-{i}" for i in range(51)]  # 5% unmatched
    assert "sites matched to a FLOC" in _failed(t)


def test_bad_locations_and_scores_fail():
    t = _tables()
    t["sites"].loc[:100, "lat"] = 0.0  # in the sea off Africa
    t["site_scores"].loc[0, "score"] = 140.0
    assert {"locations present and in Great Britain", "scores in 0–100"} <= _failed(t)


def test_missing_licence_or_future_date_fails():
    t = _tables()
    t["field_sources"].loc[0, "licence"] = ""
    assert "every field has a dataset, publish date and licence" in _failed(t)
    t = _tables()
    t["field_sources"].loc[0, "publish_date"] = "2999-01-01"
    assert "every field has a dataset, publish date and licence" in _failed(t)


def test_dataset_halving_between_snapshots_fails(tmp_path):
    for day, rows in [("2026-11-17", {"a": 1000, "b": 50}), ("2026-11-24", {"a": 500})]:
        d = tmp_path / "ukpn" / day
        d.mkdir(parents=True)
        (d / "_manifest.json").write_text(json.dumps({k: {"rows": v} for k, v in rows.items()}))
    res = {c.name: c for c in checks.check_bronze("UKPN", tmp_path)}
    assert not res["rows: a"].ok  # 1000 -> 500
    assert not res["no dataset missing from the latest snapshot"].ok  # b disappeared
