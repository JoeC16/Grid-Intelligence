"""normalise.py against a tiny fake DNO (5 sites, 2 GSPs)."""

import pandas as pd
import pytest

from pipeline.adapters.base import DNOAdapter, Source
from pipeline.normalise import build_all, build_sites, headroom_by_scenario, scenario_slug


class FakeAdapter(DNOAdapter):
    dno = "FAKE"
    default_scenario = "Holistic Transition"

    def __init__(self, sites=None):
        self._sites = sites

    def fetch_sites(self):
        if self._sites is not None:
            return self._sites
        return pd.DataFrame({
            "site_id": ["A", "B", "C", "D", "E"],
            "name": ["Alpha 11kV", "Bravo 11kV", "Charlie 11kV", "Delta 11kV", "Echo 11kV"],
            "lat": [51.5, 51.6, 51.7, 51.8, 51.9],
            "lon": [-0.1, -0.2, -0.3, -0.4, -0.5],
            "voltage_kv": [11.0] * 5,
            "licence_area": ["LPN", "LPN", "SPN", "SPN", "EPN"],
            "gsp": ["NORTH", "NORTH", "SOUTH", "SOUTH", None],
            "gsp_mapped": [True, True, True, True, False],
            "exclude_reason": [None, None, None, None, "GSP unmapped"],
        })

    def fetch_headroom(self):
        # D has no LTDS load data
        return pd.DataFrame({
            "site_id": ["A", "B", "C", "E"],
            "firm_capacity_mw": [20.0, 30.0, 10.0, 15.0],
            "observed_peak_mw": [18.0, 10.0, 11.0, 5.0],
            "demand_headroom_mw": [2.0, 20.0, -1.0, 10.0],
        })

    def fetch_future_headroom(self):
        rows = []
        for site, base in {"A": 1.0, "B": 15.0, "C": -3.0, "E": 8.0}.items():  # D missing
            for scenario, delta in {"Holistic Transition": 0.0, "Counterfactual": 1.0}.items():
                rows.append((site, scenario, 2030, base + delta))
                rows.append((site, scenario, 2035, base + delta - 5))
        return pd.DataFrame(rows, columns=["site_id", "scenario", "year", "headroom_mw"])

    def fetch_queue(self):
        return pd.DataFrame({
            "site_id": ["A", "B", "C", "D", "E"],
            "queue_mw": [12.0, 0.0, 5.0, 3.0, 7.0],
            "queue_source": ["t6", "none", "t6", "heatmap", "t6"],
            "connections_last_year": [2, 0, 1, 1, 0],
        })

    def fetch_gsp_queue(self):
        return pd.DataFrame({"gsp": ["NORTH", "(unmapped)"], "queue_mw": [100.0, 4.0]})

    def fetch_large_demand(self):
        return pd.DataFrame({
            "project_id": ["P1", "P2", "P3"],
            "licence_area": ["LPN", "LPN", "SPN"],
            "gsp": ["NORTH", "NORTH", "SOUTH"],
            "technology": ["large_demand", "der", "large_demand"],
            "import_capacity_mva": [50.0, 20.0, 10.0],
            "application_date": pd.to_datetime(["2024-01-01", "2024-06-01", "2023-01-01"]).date,
        })

    def fetch_gsps(self):
        return pd.DataFrame({
            "gsp": ["NORTH", "SOUTH"],
            "licence_area": ["LPN", "SPN"],
            "lat": [51.55, 51.75],
            "lon": [-0.15, -0.35],
            "import_capacity_utilisation_pct": [104.0, 20.0],
            "technical_limit_rag": ["RED", "GREEN"],
        })

    def fetch_topology(self):
        # BSP:1 (published headroom 25 MW) feeds A and B; BSP:2 is unmatched and
        # feeds D; C and E are fed directly from their GSP.
        bsps = pd.DataFrame({
            "bsp_id": ["BSP:1", "BSP:2"], "name": ["North Grid", "South Group"],
            "licence_area": ["LPN", "SPN"], "lat": [51.56, 51.76], "lon": [-0.16, -0.36],
            "site_id": [None, None], "gsp": ["NORTH", "SOUTH"],
            "headroom_mw": [25.0, None], "headroom_source": ["fake-heatmap", None],
            "matched": [True, False], "note": [None, "not published"],
        })
        links = pd.DataFrame({"site_id": ["A", "B", "C", "D", "E"],
                              "bsp_id": ["BSP:1", "BSP:1", None, "BSP:2", None]})
        return bsps, links

    def sources(self):
        s = Source("fake-heatmap", "2026-10-19", "https://example.org/fake-heatmap")
        return {"demand_headroom_mw": s, "queue_mw": Source("fake-t6", "2026-05-29", "https://example.org/t6")}


@pytest.fixture
def sites():
    return build_sites(FakeAdapter()).set_index("site_id")


def test_one_row_per_site(sites):
    assert list(sites.index) == ["A", "B", "C", "D", "E"]


def test_signals_merged(sites):
    assert sites.loc["A", "firm_capacity_mw"] == 20.0
    assert sites.loc["C", "demand_headroom_mw"] == -1.0
    assert sites.loc["A", "queue_mw"] == 12.0
    assert sites.loc["D", "queue_source"] == "heatmap"


def test_headroom_2030_uses_default_scenario_and_keeps_all(sites):
    assert sites.loc["A", "headroom_2030_mw"] == 1.0  # Holistic Transition
    assert sites.loc["A", "headroom_2030_counterfactual"] == 2.0
    assert sites.loc["A", "headroom_2030_holistic_transition"] == 1.0
    assert (sites["headroom_2030_scenario"] == "Holistic Transition").all()


def test_missing_signals_flagged(sites):
    assert pd.isna(sites.loc["A", "missing_signals"])
    assert sites.loc["D", "missing_signals"] == (
        "firm_capacity_mw,demand_headroom_mw,observed_peak_mw,headroom_2030_mw"
    )


def test_unmapped_gsp_not_scorable(sites):
    assert not sites.loc["E", "scorable"]
    assert sites.loc["E", "exclude_reason"] == "GSP unmapped"
    assert sites.loc[["A", "B", "C", "D"], "scorable"].all()


def test_source_columns(sites):
    assert (sites["source_dataset"] == "fake-heatmap").all()
    assert (sites["source_date"] == "2026-10-19").all()
    assert sites.loc["A", "dno"] == "FAKE"


def test_duplicate_site_ids_rejected():
    dup = FakeAdapter().fetch_sites()
    dup.loc[1, "site_id"] = "A"
    with pytest.raises(ValueError, match="duplicate"):
        build_sites(FakeAdapter(sites=dup))


def test_missing_column_rejected():
    bad = FakeAdapter().fetch_sites().drop(columns=["lat"])
    with pytest.raises(ValueError, match="lat"):
        build_sites(FakeAdapter(sites=bad))


def test_gsp_rollup():
    gsps = build_all(FakeAdapter())["gsps"].set_index("gsp")
    north, south = gsps.loc["NORTH"], gsps.loc["SOUTH"]
    assert north["site_count"] == 2
    assert north["primary_queue_mw"] == 12.0           # A + B
    assert north["grid_level_queue_mw"] == 100.0
    assert north["queue_mw"] == 112.0
    assert north["large_demand_count"] == 1 and north["large_demand_mva"] == 50.0
    assert north["der_import_count"] == 1 and north["der_import_mva"] == 20.0
    assert south["primary_queue_mw"] == 8.0            # C + D
    assert south["grid_level_queue_mw"] == 0.0
    # E (unmapped) is not rolled into any GSP; unmapped grid queue kept visibly
    assert gsps["site_count"].sum() == 4
    assert not gsps.loc["(unmapped)", "in_gsp_list"]


def test_headroom_by_scenario_wide():
    future = FakeAdapter().fetch_future_headroom()
    wide = headroom_by_scenario(future, 2035).set_index("site_id")
    assert wide.loc["B", "headroom_2035_holistic_transition"] == 10.0


def test_scenario_slug():
    assert scenario_slug("Holistic Transition") == "holistic_transition"
