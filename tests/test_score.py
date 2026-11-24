"""score.py with a 5-row fixture."""

import pandas as pd
import pytest

from pipeline.score import Signal, View, add_derived, combine, filter_rank, load_config, percentile, score

SIGNALS = [
    Signal("stuck_mw", "stuck_mw", "high", "Stuck"),
    Signal("oversubscription", "oversubscription", "high", "Oversub"),
    Signal("headroom_tightness", "demand_headroom_mw", "low", "Headroom"),
    Signal("utilisation", "utilisation", "high", "Utilisation"),
    Signal("recent_activity", "connections_last_year", "high", "Activity"),
    Signal("future_squeeze", "headroom_2030_mw", "low", "2030"),
]
WEIGHTS = {"stuck_mw": 25, "oversubscription": 20, "headroom_tightness": 15,
           "utilisation": 15, "recent_activity": 10, "future_squeeze": 15}
INVESTOR = View("investor", "weighted", "Investor", score_label="Stuck", weights=WEIGHTS)
DEVELOPER = View("developer", "filter_rank", "Developer", load_mw_default=5.0,
                 filter_column="demand_headroom_mw", rank_by="headroom_after_queue_mw")
VIEWS = [INVESTOR, DEVELOPER]


@pytest.fixture
def sites():
    # A is stuck on every signal, E is the least stuck. D lacks firm capacity
    # (so no utilisation). X is excluded and must not affect ranks.
    return pd.DataFrame({
        "site_id":               ["A",   "B",  "C",  "D",  "E",   "X"],
        "queue_mw":              [40.0, 20.0, 10.0,  5.0,  0.0, 999.0],
        "demand_headroom_mw":    [-2.0,  1.0,  4.0,  8.0, 20.0, -99.0],
        "observed_peak_mw":      [22.0, 18.0, 12.0,  6.0,  5.0,  50.0],
        "firm_capacity_mw":      [20.0, 20.0, 20.0, None, 25.0,  10.0],
        "connections_last_year": [3,     2,    1,    0,    0,    9],
        "headroom_2030_mw":      [-5.0, -1.0,  2.0,  6.0, 15.0, -50.0],
        "scorable":              [True, True, True, True, True, False],
    })


@pytest.fixture
def scored(sites):
    return score(sites, SIGNALS, VIEWS).set_index("site_id")


def test_excluded_sites_not_scored(scored):
    assert "X" not in scored.index
    assert len(scored) == 5


def test_investor_scores_in_range_and_ordered(scored):
    assert scored["score"].between(0, 100).all()
    assert scored.loc["A", "score"] == 100.0
    assert scored.loc["E", "score"] < scored.loc["D", "score"] < scored.loc["C", "score"]
    assert scored.loc["A", "rank"] == 1


def test_derived_signals(sites):
    d = add_derived(sites).set_index("site_id")
    # A: queue 40, headroom -2 -> 42 MW stuck; headroom floored at 1 for the ratio
    assert d.loc["A", "stuck_mw"] == 42.0
    assert d.loc["A", "oversubscription"] == 40.0
    # B: queue 20, headroom 1 -> 19 stuck, 20x
    assert d.loc["B", "stuck_mw"] == 19.0 and d.loc["B", "oversubscription"] == 20.0
    # D: queue 5, headroom 8 -> nothing stuck, 0.625x
    assert d.loc["D", "stuck_mw"] == 0.0
    assert d.loc["D", "oversubscription"] == pytest.approx(0.625)
    assert d.loc["E", "headroom_after_queue_mw"] == 20.0
    assert d.loc["C", "headroom_after_queue_mw"] == -6.0


def test_developer_filter_and_rank(scored):
    # load 5 MW: only D (8 MW) and E (20 MW) have enough published headroom
    ranked = scored["developer_rank"].dropna()
    assert set(ranked.index) == {"D", "E"}
    assert scored.loc["E", "developer_rank"] == 1  # 20 - 0 beats 8 - 5
    assert scored.loc["D", "developer_rank"] == 2
    assert pd.isna(scored.loc["A", "developer_rank"])


def test_stuck_rank(scored):
    # stuck MW: A 42, B 19, C 6 (10 - 4), D 0, E 0 -> D and E unranked
    assert scored.loc[["A", "B", "C"], "stuck_rank"].tolist() == [1, 2, 3]
    assert scored.loc[["D", "E"], "stuck_rank"].isna().all()


def test_developer_load_size_changes_eligibility(sites):
    df = add_derived(sites[sites["scorable"]]).set_index("site_id")
    assert filter_rank(df, DEVELOPER, 10).dropna().index.tolist() == ["E"]
    assert filter_rank(df, DEVELOPER, 0).dropna().size == 4  # B, C, D, E have headroom >= 0
    assert filter_rank(df, DEVELOPER, 100).dropna().empty


def test_low_direction_inverts(scored):
    assert scored.loc["A", "pct_headroom_tightness"] == 1.0
    assert scored.loc["E", "pct_headroom_tightness"] == 0.0


def test_utilisation_derived(scored):
    assert scored.loc["A", "utilisation"] == pytest.approx(1.1)
    assert pd.isna(scored.loc["D", "utilisation"])


def test_missing_signal_scored_on_rest_and_flagged(scored):
    d = scored.loc["D"]
    assert d["score_missing"] == "utilisation"
    assert d["signals_used"] == 5  # of 6
    expected = 100 * (25 * d.pct_stuck_mw + 20 * d.pct_oversubscription + 15 * d.pct_headroom_tightness
                      + 10 * d.pct_recent_activity + 15 * d.pct_future_squeeze) / 85
    assert d["score"] == pytest.approx(expected, abs=0.05)
    assert pd.isna(scored.loc["A", "score_missing"])


def test_ties_share_lowest_rank():
    p = percentile(pd.Series([0.0, 0.0, 5.0, 10.0]), "high")
    assert list(p) == [0.0, 0.0, pytest.approx(2 / 3), 1.0]


def test_percentile_keeps_nan():
    p = percentile(pd.Series([1.0, None, 3.0]), "low")
    assert p.iloc[0] == 1.0 and pd.isna(p.iloc[1]) and p.iloc[2] == 0.0


def test_combine_custom_weights(scored):
    # Only recent activity counts: B (2 offers) beats C (1).
    only_activity = {s.key: (1 if s.key == "recent_activity" else 0) for s in SIGNALS}
    s = combine(scored, only_activity)
    assert s["B"] > s["C"]


def test_config_loads():
    signals, views = load_config()
    by_key = {v.key: v for v in views}
    assert views[0].key == "investor" and views[0].type == "weighted"
    assert by_key["investor"].weights == WEIGHTS
    dev = by_key["developer"]
    assert dev.type == "filter_rank"
    assert dev.load_mw_default == 50
    assert (dev.filter_column, dev.rank_by, dev.rank_by_local) == (
        "demand_headroom_mw", "effective_headroom_mw", "headroom_after_queue_mw")


def test_scores_and_ranks_are_per_country():
    from pipeline.score import load_config, score
    signals, views = load_config()
    n = 4
    rows = []
    for country, base in [("GB", 0.0), ("ES", 100.0)]:
        for i in range(n):
            rows.append({"site_id": f"{country}{i}", "country": country, "scorable": True,
                         "queue_mw": base + i, "demand_headroom_mw": 5.0 - i, "firm_capacity_mw": 10.0,
                         "observed_peak_mw": 5.0 + i, "connections_last_year": i, "headroom_2030_mw": 3.0 - i,
                         "effective_headroom_mw": 5.0 - i - (base + i)})
    s = score(pd.DataFrame(rows), signals, views).set_index("site_id")
    # Each country has its own rank 1, and the same relative position gets the same score.
    assert s.loc["GB3", "rank"] == 1 and s.loc["ES3", "rank"] == 1
    assert s.loc["GB3", "score"] == s.loc["ES3", "score"]


def test_capacity_taken_gives_utilisation_where_peak_missing():
    from pipeline.score import add_derived
    df = pd.DataFrame({"queue_mw": [1.0], "demand_headroom_mw": [20.0], "firm_capacity_mw": [float("nan")],
                       "observed_peak_mw": [float("nan")], "capacity_taken_mw": [60.0]})
    assert add_derived(df)["utilisation"].iloc[0] == pytest.approx(0.75)
