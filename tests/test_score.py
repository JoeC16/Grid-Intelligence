"""score.py with a 5-row fixture."""

import pandas as pd
import pytest

from pipeline.score import Signal, load_signals, percentile, score

SIGNALS = [
    Signal("queue_pressure", 30, "queue_mw", "high", "Queue"),
    Signal("headroom_tightness", 25, "demand_headroom_mw", "low", "Headroom"),
    Signal("utilisation", 15, "utilisation", "high", "Utilisation"),
    Signal("recent_activity", 15, "connections_last_year", "high", "Activity"),
    Signal("future_squeeze", 15, "headroom_2030_mw", "low", "2030"),
]


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
    return score(sites, SIGNALS).set_index("site_id")


def test_excluded_sites_not_scored(scored):
    assert "X" not in scored.index
    assert len(scored) == 5


def test_scores_in_range_and_ordered(scored):
    assert scored["score"].between(0, 100).all()
    assert scored.loc["A", "score"] == 100.0
    assert scored.loc["E", "score"] < scored.loc["D", "score"] < scored.loc["C", "score"]
    assert scored.loc["A", "rank"] == 1


def test_low_direction_inverts(scored):
    # A has the least headroom, so the highest tightness percentile.
    assert scored.loc["A", "pct_headroom_tightness"] == 1.0
    assert scored.loc["E", "pct_headroom_tightness"] == 0.0


def test_utilisation_derived(scored):
    assert scored.loc["A", "utilisation"] == pytest.approx(1.1)
    assert pd.isna(scored.loc["D", "utilisation"])


def test_missing_signal_scored_on_rest_and_flagged(scored, sites):
    d = scored.loc["D"]
    assert d["score_missing"] == "utilisation"
    assert d["signals_used"] == 4
    # weights re-normalised over the 85 points D has
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


def test_weights_change_ranking(sites):
    # Only recent activity counts: B (2) beats C (1).
    only_activity = [Signal(s.key, 1 if s.key == "recent_activity" else 0, s.column, s.direction, s.label)
                     for s in SIGNALS]
    r = score(sites, only_activity).set_index("site_id")
    assert r.loc["B", "score"] > r.loc["C", "score"]


def test_config_loads():
    signals = {s.key: s for s in load_signals()}
    assert {k: s.weight for k, s in signals.items()} == {
        "queue_pressure": 30, "headroom_tightness": 25, "utilisation": 15,
        "recent_activity": 15, "future_squeeze": 15,
    }
