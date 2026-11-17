"""Scores, 0-100, for each scorable site, one per view in config/weights.yaml.

Usage:  uv run python -m pipeline.score     # score data/grid.duckdb, print top 20

Method:
  1. Derive utilisation = observed_peak_mw / firm_capacity_mw.
  2. Percentile-rank each signal across scorable sites, oriented so 1 = most
     stuck. Ties share the lowest rank, so e.g. every zero-queue site gets 0.
  3. Per view: use p (or 1 - p if the view inverts), take the weighted sum of
     the signals a site has, divide by those signals' weights, times 100.
     Missing signals are listed in score_missing.

The first view (investor) is stored as score / rank; the others as
<view>_score / <view>_rank. The web app repeats step 3 in the browser so the
weight sliders re-rank live (web/src/scoring.ts) — keep the two in step.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_PATH = ROOT / "config" / "weights.yaml"
DB_PATH = ROOT / "data" / "grid.duckdb"


@dataclass(frozen=True)
class Signal:
    key: str
    column: str
    direction: str  # "high" or "low"
    label: str
    description: str = ""


@dataclass(frozen=True)
class View:
    key: str
    label: str
    score_label: str
    invert: bool
    weights: dict[str, float] = field(default_factory=dict)
    description: str = ""


def load_config(path: Path = WEIGHTS_PATH) -> tuple[list[Signal], list[View]]:
    raw = yaml.safe_load(path.read_text())
    signals = [
        Signal(k, s["column"], s["direction"], s.get("label", k), s.get("description", ""))
        for k, s in raw["signals"].items()
    ]
    keys = {s.key for s in signals}
    for s in signals:
        if s.direction not in ("high", "low"):
            raise ValueError(f"{s.key}: direction must be 'high' or 'low', got {s.direction!r}")
    views = []
    for k, v in raw["views"].items():
        weights = {sk: float(w) for sk, w in v["weights"].items()}
        unknown = set(weights) - keys
        if unknown:
            raise ValueError(f"view {k}: unknown signals {sorted(unknown)}")
        if any(w < 0 for w in weights.values()) or not any(weights.values()):
            raise ValueError(f"view {k}: weights must be >= 0 and not all zero")
        views.append(View(k, v.get("label", k), v.get("score_label", k), bool(v.get("invert", False)),
                          {s.key: weights.get(s.key, 0.0) for s in signals}, v.get("description", "")))
    return signals, views


def add_derived(sites: pd.DataFrame) -> pd.DataFrame:
    df = sites.copy()
    firm = df["firm_capacity_mw"].where(df["firm_capacity_mw"] > 0)
    df["utilisation"] = df["observed_peak_mw"] / firm
    return df


def percentile(values: pd.Series, direction: str) -> pd.Series:
    """0..1 rank, 1 = most stuck. NaN stays NaN. Ties take the lowest rank."""
    oriented = values if direction == "high" else -values
    n = oriented.notna().sum()
    if n == 1:  # a lone value can't be ranked against anything
        return oriented.notna().astype(float).where(oriented.notna())
    ranks = oriented.rank(method="min")
    return (ranks - 1) / (n - 1)


def combine(pcts: pd.DataFrame, weights: dict[str, float], invert: bool) -> pd.Series:
    """Weighted 0-100 score from pct_<signal> columns; re-normalise over present signals."""
    cols = [f"pct_{k}" for k in weights]
    w = pd.Series({f"pct_{k}": v for k, v in weights.items()})
    p = pcts[cols]
    if invert:
        p = 1 - p
    present = p.notna()
    available = present.mul(w).sum(axis=1)
    weighted = p.fillna(0).mul(w).sum(axis=1)
    raw = 100 * weighted / available.where(available > 0)
    # Round half-up to 1 dp, in the same order as web/src/scoring.ts.
    return np.floor(raw * 10 + 0.5) / 10


def score(sites: pd.DataFrame, signals: list[Signal], views: list[View]) -> pd.DataFrame:
    """site_id, score + rank per view, pct_<signal>, raw signal values, score_missing."""
    df = add_derived(sites)
    df = df[df["scorable"]].copy()

    pct_cols = []
    for s in signals:
        df[f"pct_{s.key}"] = percentile(df[s.column], s.direction)
        pct_cols.append(f"pct_{s.key}")

    score_cols = []
    for i, v in enumerate(views):
        prefix = "" if i == 0 else f"{v.key}_"
        df[f"{prefix}score"] = combine(df, v.weights, v.invert)
        df[f"{prefix}rank"] = df[f"{prefix}score"].rank(ascending=False, method="min").astype("Int64")
        score_cols += [f"{prefix}score", f"{prefix}rank"]

    present = df[pct_cols].notna()
    df["signals_used"] = present.sum(axis=1)
    df["score_missing"] = present.apply(
        lambda row: ",".join(s.key for s in signals if not row[f"pct_{s.key}"]) or None, axis=1
    )

    raw_cols = list(dict.fromkeys(s.column for s in signals))
    keep = ["site_id", *score_cols, "signals_used", "score_missing", *pct_cols, *raw_cols]
    return df[keep].sort_values([score_cols[1], "site_id"]).reset_index(drop=True)


def write_scores(con: duckdb.DuckDBPyConnection, scores: pd.DataFrame, views: list[View]) -> None:
    con.register("_scores", scores)
    con.execute("CREATE OR REPLACE TABLE site_scores AS SELECT * FROM _scores")
    con.unregister("_scores")
    weights = pd.DataFrame(
        [{"view": v.key, "invert": v.invert, "key": k, "weight": w} for v in views for k, w in v.weights.items()]
    )
    con.register("_w", weights)
    con.execute("CREATE OR REPLACE TABLE score_weights AS SELECT * FROM _w")
    con.unregister("_w")


def print_top(con: duckdb.DuckDBPyConnection, n: int = 20, view: str = "investor") -> None:
    prefix = "" if view == "investor" else f"{view}_"
    top = con.execute(
        f"""
        SELECT s.{prefix}rank AS rank, s.{prefix}score AS score, t.name, t.licence_area AS area, t.gsp,
               round(t.queue_mw, 1) AS queue_mw,
               round(t.demand_headroom_mw, 1) AS headroom_mw,
               round(s.utilisation * 100) AS util_pct,
               t.connections_last_year AS accepted_1y,
               round(t.headroom_2030_mw, 1) AS headroom_2030_mw,
               s.score_missing
        FROM site_scores s JOIN sites t USING (site_id)
        ORDER BY s.{prefix}rank, t.site_id
        LIMIT {int(n)}
        """
    ).df()
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 38):
        print(top.to_string(index=False))


def main() -> None:
    signals, views = load_config()
    with duckdb.connect(str(DB_PATH)) as con:
        scores = score(con.execute("SELECT * FROM sites").df(), signals, views)
        write_scores(con, scores, views)
        print(f"Scored {len(scores)} sites; {scores['score_missing'].notna().sum()} scored on partial signals.")
        for v in views:
            print(f"\nTop 20 — {v.label} view ({v.score_label}):")
            print_top(con, view=v.key)


if __name__ == "__main__":
    main()
