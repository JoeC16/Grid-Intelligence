"""Data quality checks catch the failures they are meant to (Phase 11)."""

import json

import pandas as pd

from pipeline import checks


def _dno(code="UKPN", min_sites=900, prefix="UKPN-MRID-"):
    return {"code": code, "min_sites": min_sites, "fallback_id_prefix": prefix, "lat_min": 49.5, "lat_max": 61.0,
            "lon_min": -8.7, "lon_max": 2.1, "min_scorable_share": 0.98, "has_topology": True}


def _tables(n=1000, dno="UKPN", prefix=""):
    sites = pd.DataFrame({
        "site_id": [f"{prefix}EPN-S{i:06d}" for i in range(n)],
        "dno": [dno] * n,
        "lat": [51.5] * n, "lon": [0.1] * n,
        "scorable": [True] * n, "gsp_mapped": [True] * n,
        "demand_headroom_mw": [5.0] * n, "queue_mw": [1.0] * n,
        "bsp_id": [None] * n, "bsp_headroom_mw": [None] * n,
    })
    bsps = pd.DataFrame({"matched": [True] * 10, "dno": [dno] * 10})
    fs = pd.DataFrame({"dno": [dno], "dataset_id": ["ds"], "publish_date": ["2026-10-19"], "licence": ["CC BY 4.0"]})
    sc = pd.DataFrame({"score": [50.0] * n, "rank": list(range(1, n + 1))})
    gsps = pd.DataFrame({"gsp": [f"{dno} GSP {i}" for i in range(5)], "dno": [dno] * 5})
    return {"sites": sites, "bsps": bsps, "field_sources": fs, "site_scores": sc, "gsps": gsps,
            "dnos": pd.DataFrame([_dno(dno)])}


def _failed(t):
    return {c.name for c in checks.check_tables(t) if not c.ok}


def test_clean_tables_pass():
    assert _failed(_tables()) == set()


def test_broken_join_fails():
    t = _tables()
    t["sites"].loc[:50, "site_id"] = [f"UKPN-MRID-{i}" for i in range(51)]  # 5% unmatched
    assert "UKPN: sites matched to a stable ID" in _failed(t)


def test_bad_locations_and_scores_fail():
    t = _tables()
    t["sites"].loc[:100, "lat"] = 0.0  # in the sea off Africa
    t["site_scores"].loc[0, "score"] = 140.0
    assert {"UKPN: locations present and in its area", "scores in 0–100"} <= _failed(t)


def test_missing_licence_or_future_date_fails():
    t = _tables()
    t["field_sources"].loc[0, "licence"] = ""
    assert "UKPN: every field has a dataset, publish date and licence" in _failed(t)
    t = _tables()
    t["field_sources"].loc[0, "publish_date"] = "2999-01-01"
    assert "UKPN: every field has a dataset, publish date and licence" in _failed(t)


def test_dataset_halving_between_snapshots_fails(tmp_path):
    for day, rows in [("2026-11-17", {"a": 1000, "b": 50}), ("2026-11-24", {"a": 500})]:
        d = tmp_path / "ukpn" / day
        d.mkdir(parents=True)
        (d / "_manifest.json").write_text(json.dumps({k: {"rows": v} for k, v in rows.items()}))
    res = {c.name: c for c in checks.check_bronze("UKPN", tmp_path)}
    assert not res["UKPN: rows: a"].ok  # 1000 -> 500
    assert not res["UKPN: no dataset missing from the latest snapshot"].ok  # b disappeared


def test_snapshot_diff(tmp_path):
    from pipeline.snapshot_diff import changed
    a, b, c = (tmp_path / x for x in "abc")
    for d, m in [(a, {"ds": {"modified": "2026-10-19", "rows": 5}}), (b, {"ds": {"modified": "2026-10-19", "rows": 5}}),
                 (c, {"ds": {"modified": "2026-11-30", "rows": 6}})]:
        d.mkdir()
        (d / "_manifest.json").write_text(json.dumps(m))
    assert not changed(a, b) and changed(b, c)


def test_each_dno_checked_against_its_own_thresholds():
    a, b = _tables(1000, "UKPN"), _tables(300, "SPEN", prefix="SPEN-")
    t = {k: pd.concat([a[k], b[k]], ignore_index=True) for k in a}
    t["dnos"] = pd.DataFrame([_dno("UKPN"), _dno("SPEN", min_sites=250, prefix="SPEN-X-")])
    assert _failed(t) == set()
    t["dnos"].loc[1, "min_sites"] = 400  # SPEN download came back short
    assert _failed(t) == {"SPEN: sites present"}


def test_gsp_name_clash_and_undescribed_dno_fail():
    a, b = _tables(1000, "UKPN"), _tables(1000, "SPEN", prefix="SPEN-")
    b["gsps"].loc[0, "gsp"] = "UKPN GSP 0"
    t = {k: pd.concat([a[k], b[k]], ignore_index=True) for k in a}
    t["dnos"] = pd.DataFrame([_dno("UKPN")])  # SPEN rows but no SPEN description
    assert {"GSP names unique", "every site's DNO is described"} <= _failed(t)
