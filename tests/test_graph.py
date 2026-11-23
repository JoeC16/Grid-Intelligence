"""graph.py: upstream constraints on a small fixture (the fake DNO from test_normalise)."""

import pandas as pd
import pytest

from pipeline import graph
from pipeline.normalise import build_all
from tests.test_normalise import FakeAdapter


@pytest.fixture(scope="module")
def tables():
    return build_all(FakeAdapter())


@pytest.fixture(scope="module")
def sites(tables):
    return tables["sites"].set_index("site_id")


def test_bsp_rollup(tables):
    b = tables["bsps"].set_index("bsp_id")
    # BSP:1 feeds A (queue 12) and B (queue 0); published headroom 25
    assert b.loc["BSP:1", "site_count"] == 2
    assert b.loc["BSP:1", "queue_mw"] == 12.0
    assert b.loc["BSP:1", "headroom_after_queue_mw"] == 13.0
    assert b.loc["BSP:1", "stuck_mw"] == 0.0  # 12 queued < 25 headroom
    # BSP:2 isn't published: its queue still rolls up, nothing else is computed
    assert b.loc["BSP:2", "queue_mw"] == 3.0
    assert pd.isna(b.loc["BSP:2", "headroom_after_queue_mw"]) and pd.isna(b.loc["BSP:2", "stuck_mw"])


def test_site_limited_by_bsp(sites):
    # B: 20 MW headroom, nothing queued locally, but only 13 MW left at its BSP
    b = sites.loc["B"]
    assert b["effective_headroom_mw"] == 13.0
    assert b["limiting_level"] == "bsp" and b["upstream_constrained"]


def test_site_limited_by_itself(sites):
    # A: 2 MW headroom, 12 MW queued -> -10 locally, tighter than the BSP's 13
    a = sites.loc["A"]
    assert a["effective_headroom_mw"] == -10.0
    assert a["limiting_level"] == "primary" and not a["upstream_constrained"]


def test_direct_fed_site(sites):
    # C: fed straight from the GSP; -1 MW headroom, 5 MW queued
    c = sites.loc["C"]
    assert pd.isna(c["bsp_id"]) and c["effective_headroom_mw"] == -6.0 and c["limiting_level"] == "primary"


def test_unpublished_bsp_and_missing_local(sites):
    # D sits under the unpublished BSP and has no published headroom itself
    d = sites.loc["D"]
    assert d["bsp_id"] == "BSP:2" and pd.isna(d["effective_headroom_mw"]) and pd.isna(d["limiting_level"])


def test_gsp_flag(sites):
    # NORTH's peak is 104% of capacity; SOUTH's 20%. The RAG (RED for NORTH) is ignored.
    assert sites.loc["A", "gsp_over_capacity"] and sites.loc["B", "gsp_over_capacity"]
    assert not sites.loc["C", "gsp_over_capacity"]


def test_edges(tables):
    e = {(r.child_id, r.parent_id) for r in tables["edges"].itertuples()}
    assert e == {("A", "BSP:1"), ("B", "BSP:1"), ("C", "GSP:SOUTH"), ("D", "BSP:2"),
                 ("BSP:1", "GSP:NORTH"), ("BSP:2", "GSP:SOUTH")}  # E has no BSP and no GSP


def test_bsp_own_board_points_to_gsp_not_itself():
    sites = pd.DataFrame({"site_id": ["X", "Y"], "gsp": ["G", "G"], "demand_headroom_mw": [30.0, 5.0],
                          "queue_mw": [4.0, 2.0]})
    bsps = pd.DataFrame({"bsp_id": ["BSP:X"], "name": ["X Grid"], "licence_area": ["LPN"], "lat": [0.0],
                         "lon": [0.0], "site_id": ["X"], "gsp": ["G"], "headroom_mw": [30.0],
                         "headroom_source": ["ds"], "matched": [True], "note": [None]})
    links = pd.DataFrame({"site_id": ["X", "Y"], "bsp_id": ["BSP:X", "BSP:X"]})
    out = graph.build(sites, bsps, links, pd.DataFrame({"gsp": ["G"], "import_capacity_utilisation_pct": [50.0]}))
    e = {(r.child_id, r.parent_id) for r in out["edges"].itertuples()}
    assert ("X", "GSP:G") in e and ("X", "BSP:X") not in e and ("Y", "BSP:X") in e
    s = out["sites"].set_index("site_id")
    # X's own queue counts at the BSP: 30 - (4 + 2) = 24 effective for X
    assert s.loc["X", "effective_headroom_mw"] == 24.0 and s.loc["X", "limiting_level"] == "bsp"
