"""Unlock planner on a tiny tree (Phase 15)."""

import pandas as pd
import pytest

from pipeline import unlock


def _tree(h=50.0):
    # Node: published headroom h. Sites under it: own headroom − own queue.
    sites = pd.DataFrame({
        "site_id": ["a", "b", "c", "d"], "bsp_id": ["N", "N", "N", None],
        "demand_headroom_mw": [30.0, 20.0, 5.0, 40.0], "queue_mw": [10.0, 30.0, 0.0, 0.0],
    })
    bsps = pd.DataFrame({"bsp_id": ["N"], "dno": ["X"], "name": ["Node"], "lat": [51.0], "lon": [0.0],
                         "matched": [True], "headroom_mw": [h], "queue_mw": [40.0]})
    return sites, bsps


def test_curve_serves_queue_then_opens_capacity_without_double_counting():
    after = pd.Series([20.0, -10.0, 5.0])  # spare 25 MW at the sites; site b is short by 10
    rows = {r["added_mw"]: r for r in unlock.curve(h=30.0, q=40.0, after=after, steps=(0, 5, 10, 20, 50), needs_local=0)}
    assert rows[0]["unlocked_mw"] == 0 and rows[0]["sites_open"] == 0
    assert rows[5]["queue_served_mw"] == 5 and rows[5]["new_capacity_mw"] == 0  # queue first
    assert rows[10]["queue_served_mw"] == 10 and rows[10]["new_capacity_mw"] == 0
    assert rows[20]["new_capacity_mw"] == 10 and rows[20]["sites_open"] == 1  # node left 10 MW: site a opens
    assert rows[50]["new_capacity_mw"] == 25  # capped by spare at the sites, not 40
    assert all(r["unlocked_mw"] <= r["added_mw"] for r in rows.values())


def test_mw_to_first_open():
    after = pd.Series([20.0, 5.0])
    assert unlock.mw_to_first_open(30.0, 40.0, after, load_mw=10) == 20.0
    assert unlock.mw_to_first_open(60.0, 40.0, after, load_mw=10) == 0.0
    assert unlock.mw_to_first_open(30.0, 40.0, pd.Series([5.0, 2.0]), load_mw=10) is None  # needs local work


def test_build_mart_and_ranks():
    sites, bsps = _tree(h=30.0)
    mart, curves = unlock.build(sites, bsps, steps=(0, 10, 50), load_mw=10)
    m = mart.set_index("bsp_id").loc["N"]
    assert m["sites"] == 3 and m["node_stuck_mw"] == 10 and m["spare_mw"] == 25 and m["needs_local_mw"] == 10
    # node stuck 10 MW, all of it at site b, which is also short locally: the node alone serves none of it
    assert m["served_10"] == 0 and m["served_local_10"] == 10
    assert m["new_50"] == 25 and m["open_50"] == 1
    assert m["rank_new_50"] == 1 and pd.isna(m["rank_queue_50"])
    assert len(curves) == 3 and set(curves["bsp_id"]) == {"N"}


def test_unmatched_nodes_are_left_out():
    sites, bsps = _tree()
    bsps.loc[0, "matched"] = False
    mart, _ = unlock.build(sites, bsps)
    assert mart.empty


def test_gain_ignores_room_the_node_already_has():
    sites = pd.DataFrame({"site_id": ["a"], "bsp_id": ["N"], "demand_headroom_mw": [80.0], "queue_mw": [0.0]})
    bsps = pd.DataFrame({"bsp_id": ["N"], "dno": ["X"], "name": ["Roomy"], "lat": [0.0], "lon": [0.0],
                         "matched": [True], "headroom_mw": [200.0], "queue_mw": [0.0]})
    m = unlock.build(sites, bsps, steps=(0, 50))[0].iloc[0]
    assert m["new_0"] == 80 and m["new_50"] == 0 and m["open_50"] == 0 and pd.isna(m["rank_new_50"])


def test_node_alone_serves_only_queue_waiting_on_the_node():
    after = pd.Series([0.0])
    r = unlock.curve(h=0.0, q=30.0, after=after, steps=(0, 50), needs_local=20.0)[1]
    assert r["queue_served_mw"] == 10 and r["queue_served_with_local_mw"] == 30
