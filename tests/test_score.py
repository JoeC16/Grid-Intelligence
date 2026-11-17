"""score.py with a 5-row fixture."""

import pandas as pd
import pytest

from pipeline.score import Signal, View, combine, load_config, percentile, score

SIGNALS = [
    Signal("queue_pressure", "queue_mw", "high", "Queue"),
    Signal("headroom_tightness", "demand_headroom_mw", "low", "Headroom"),
    Signal("utilisation", "utilisation", "high", "Utilisation"),
    Signal("recent_activity", "connections_last_year", "high", "Activity"),
    Signal("future_squeeze", "headroom_2030_mw", "low", "2030"),
]
INVESTOR = View("investor", "Investor", "Stuck", False, {
    "queue_pressure": 30, "headroom_tightness": 25, "utilisation": 15, "recent_activity": 15, "future_squeeze": 15,
})
DEVELOPER = View("developer", "Developer", "Opportunity", True, {
    "queue_pressure": 50, "headroom_tightness": 50, "utilisation": 0, "recent_activity": 0, "future_squeeze": 0,
})
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


def test_developer_view_inverts_headroom_and_queue(scored):
    # E has the most headroom and no queue: the best place to connect.
    assert scored.loc["E", "developer_score"] == 100.0
    assert scored.loc["E", "developer_rank"] == 1
    assert scored.loc["A", "developer_score"] == 0.0
    # With equal weights on two inverted signals, dev score = 100 - those two signals' stuck score.
    for site in "ABCDE":
        r = scored.loc[site]
        assert r["developer_score"] == pytest.approx(
            100 * (1 - (r.pct_queue_pressure + r.pct_headroom_tightness) / 2), abs=0.05)


def test_low_direction_inverts(scored):
    assert scored.loc["A", "pct_headroom_tightness"] == 1.0
    assert scored.loc["E", "pct_headroom_tightness"] == 0.0


def test_utilisation_derived(scored):
    assert scored.loc["A", "utilisation"] == pytest.approx(1.1)
    assert pd.isna(scored.loc["D", "utilisation"])


def test_missing_signal_scored_on_rest_and_flagged(scored):
    d = scored.loc["D"]
    assert d["score_missing"] == "utilisation"
    assert d["signals_used"] == 4
    expected = 100 * (30 * d.pct_queue_pressure + 25 * d.pct_headroom_tightness
                      + 15 * d.pct_recent_activity + 15 * d.pct_future_squeeze) / 85
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
    s = combine(scored, only_activity, invert=False)
    assert s["B"] > s["C"]


def test_config_loads():
    signals, views = load_config()
    by_key = {v.key: v for v in views}
    assert [v.key for v in views][0] == "investor"
    assert by_key["investor"].weights == {
        "queue_pressure": 30, "headroom_tightness": 25, "utilisation": 15,
        "recent_activity": 15, "future_squeeze": 15,
    }
    dev = by_key["developer"]
    assert dev.invert
    assert {k for k, w in dev.weights.items() if w} == {"queue_pressure", "headroom_tightness"}
