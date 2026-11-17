"""Scores, 0-100, for each scorable site, one per view in config/weights.yaml.

Usage:  uv run python -m pipeline.score     # score data/grid.duckdb, print top 20

Method (full explanation in docs/SCORING.md):
  1. Derive utilisation, stuck_mw, oversubscription, headroom_after_queue_mw.
  2. Percentile-rank each signal across scorable sites, oriented so 1 = most
     stuck. Ties share the lowest rank, so e.g. every zero-stuck site gets 0.
  3. Weighted views: weighted sum of the percentiles a site has, divided by
     those signals' weights, times 100. Missing signals go in score_missing.
     Filter-rank views: keep sites where filter_column >= load size, rank by
     rank_by, highest first. No score.

The first weighted view (investor) is stored as score / rank. A filter-rank
view is stored as <view>_rank at its default load size. The web app repeats
step 3 in the browser so sliders and the load-size input re-rank live
(web/src/scoring.ts) — keep the two in step.
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
    type: str  # "weighted" or "filter_rank"
    label: str
    description: str = ""
    # weighted
    score_label: str = ""
    weights: dict[str, float] = field(default_factory=dict)
    # filter_rank
    load_mw_default: float = 0.0
    filter_column: str = ""
    rank_by: str = ""


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
        vtype = v.get("type", "weighted")
        if vtype == "weighted":
            weights = {sk: float(w) for sk, w in v["weights"].items()}
            unknown = set(weights) - keys
            if unknown:
                raise ValueError(f"view {k}: unknown signals {sorted(unknown)}")
            if any(w < 0 for w in weights.values()) or not any(weights.values()):
                raise ValueError(f"view {k}: weights must be >= 0 and not all zero")
            views.append(View(k, vtype, v.get("label", k), v.get("description", ""),
                              score_label=v.get("score_label", k),
                              weights={s.key: weights.get(s.key, 0.0) for s in signals}))
        elif vtype == "filter_rank":
            views.append(View(k, vtype, v.get("label", k), v.get("description", ""),
                              load_mw_default=float(v["load_mw_default"]),
                              filter_column=v["filter_column"], rank_by=v["rank_by"]))
        else:
            raise ValueError(f"view {k}: unknown type {vtype!r}")
    if not views or views[0].type != "weighted":
        raise ValueError("the first view must be a weighted view (it is stored as score / rank)")
    return signals, views


def add_derived(sites: pd.DataFrame) -> pd.DataFrame:
    df = sites.copy()
    queue, headroom = df["queue_mw"], df["demand_headroom_mw"]
    firm = df["firm_capacity_mw"].where(df["firm_capacity_mw"] > 0)
    df["utilisation"] = df["observed_peak_mw"] / firm
    # MW of queued demand that published headroom can't absorb.
    df["stuck_mw"] = (queue - headroom).clip(lower=0)
    # Queue relative to headroom; headroom floored at 1 MW so tiny or negative
    # headroom doesn't divide by ~zero.
    df["oversubscription"] = queue / headroom.clip(lower=1)
    # Developer view: headroom left after everything already queued.
    df["headroom_after_queue_mw"] = headroom - queue
    return df


def percentile(values: pd.Series, direction: str) -> pd.Series:
    """0..1 rank, 1 = most stuck. NaN stays NaN. Ties take the lowest rank."""
    oriented = values if direction == "high" else -values
    n = oriented.notna().sum()
    if n == 1:  # a lone value can't be ranked against anything
        return oriented.notna().astype(float).where(oriented.notna())
    ranks = oriented.rank(method="min")
    return (ranks - 1) / (n - 1)


def combine(pcts: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Weighted 0-100 score from pct_<signal> columns; re-normalise over present signals."""
    cols = [f"pct_{k}" for k in weights]
    w = pd.Series({f"pct_{k}": v for k, v in weights.items()})
    p = pcts[cols]
    present = p.notna()
    available = present.mul(w).sum(axis=1)
    weighted = p.fillna(0).mul(w).sum(axis=1)
    raw = 100 * weighted / available.where(available > 0)
    # Round half-up to 1 dp, in the same order as web/src/scoring.ts.
    return np.floor(raw * 10 + 0.5) / 10


def rank_desc(values: pd.Series) -> pd.Series:
    """1 = highest; ties share the best rank. Values rounded to 3 dp first so
    float noise doesn't split ties (and the browser, which gets 3 dp, agrees)."""
    return values.round(3).rank(ascending=False, method="min").astype("Int64")


def filter_rank(df: pd.DataFrame, view: View, load_mw: float) -> pd.Series:
    """Rank (1 = best) among sites with filter_column >= load_mw; NA for the rest."""
    eligible = df[view.filter_column] >= load_mw
    return rank_desc(df.loc[eligible, view.rank_by]).reindex(df.index)


def stuck_rank(df: pd.DataFrame) -> pd.Series:
    """Investor 'Most stuck MW' sort: rank by stuck_mw among sites with any stuck demand."""
    return rank_desc(df.loc[df["stuck_mw"] > 0, "stuck_mw"]).reindex(df.index)


def score(sites: pd.DataFrame, signals: list[Signal], views: list[View]) -> pd.DataFrame:
    """site_id, score/rank per view, pct_<signal>, raw signal values, score_missing."""
    df = add_derived(sites)
    df = df[df["scorable"]].copy()

    pct_cols = []
    for s in signals:
        df[f"pct_{s.key}"] = percentile(df[s.column], s.direction)
        pct_cols.append(f"pct_{s.key}")

    score_cols = []
    for i, v in enumerate(views):
        prefix = "" if i == 0 else f"{v.key}_"
        if v.type == "weighted":
            df[f"{prefix}score"] = combine(df, v.weights)
            df[f"{prefix}rank"] = df[f"{prefix}score"].rank(ascending=False, method="min").astype("Int64")
            score_cols += [f"{prefix}score", f"{prefix}rank"]
        else:
            df[f"{prefix}rank"] = filter_rank(df, v, v.load_mw_default)
            score_cols.append(f"{prefix}rank")
    df["stuck_rank"] = stuck_rank(df)
    score_cols.append("stuck_rank")

    present = df[pct_cols].notna()
    df["signals_used"] = present.sum(axis=1)
    df["score_missing"] = present.apply(
        lambda row: ",".join(s.key for s in signals if not row[f"pct_{s.key}"]) or None, axis=1
    )

    raw_cols = list(dict.fromkeys(
        [s.column for s in signals] + ["queue_mw", "headroom_after_queue_mw"]
        + [v.rank_by for v in views if v.type == "filter_rank"]))
    keep = ["site_id", *score_cols, "signals_used", "score_missing", *pct_cols, *raw_cols]
    return df[keep].sort_values([score_cols[1], "site_id"]).reset_index(drop=True)


def write_scores(con: duckdb.DuckDBPyConnection, scores: pd.DataFrame, views: list[View]) -> None:
    con.register("_scores", scores)
    con.execute("CREATE OR REPLACE TABLE site_scores AS SELECT * FROM _scores")
    con.unregister("_scores")
    weights = pd.DataFrame(
        [{"view": v.key, "key": k, "weight": w} for v in views if v.type == "weighted" for k, w in v.weights.items()]
    )
    con.register("_w", weights)
    con.execute("CREATE OR REPLACE TABLE score_weights AS SELECT * FROM _w")
    con.unregister("_w")


def print_top(con: duckdb.DuckDBPyConnection, view: View, n: int = 20, first: bool = True) -> None:
    prefix = "" if first else f"{view.key}_"
    if view.type == "weighted":
        title = f"{view.label} view: {view.score_label}"
        cols = f"""s.{prefix}rank AS rank, s.{prefix}score AS score, t.name, t.licence_area AS area, t.voltage AS kv,
               round(t.queue_mw, 1) AS queue_mw, round(t.demand_headroom_mw, 1) AS headroom_mw,
               round(s.stuck_mw, 1) AS stuck_mw, round(s.oversubscription, 1) AS oversub,
               round(s.utilisation * 100) AS util_pct, t.connections_last_year AS acc_1y,
               round(t.headroom_2030_mw, 1) AS hr_2030, s.score_missing AS missing"""
    else:
        title = (f"{view.label} view: {view.filter_column} >= {view.load_mw_default:g} MW, "
                 f"ranked by {view.rank_by}")
        cols = f"""s.{prefix}rank AS rank, t.name, t.licence_area AS area, t.voltage AS kv, t.gsp,
               round(t.demand_headroom_mw, 1) AS headroom_mw, round(t.queue_mw, 1) AS queue_mw,
               round(s.headroom_after_queue_mw, 1) AS after_queue_mw"""
    top = con.execute(
        f"""
        SELECT {cols}
        FROM site_scores s JOIN sites t USING (site_id)
        WHERE s.{prefix}rank IS NOT NULL
        ORDER BY s.{prefix}rank, t.site_id
        LIMIT {int(n)}
        """
    ).df()
    eligible = con.execute(f"SELECT count(*) FROM site_scores WHERE {prefix}rank IS NOT NULL").fetchall()[0][0]
    print(f"\nTop {n} — {title}  ({eligible} sites ranked)")
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 30):
        print(top.to_string(index=False))


def print_all_tops(con: duckdb.DuckDBPyConnection, views: list[View], n: int = 20) -> None:
    for i, v in enumerate(views):
        print_top(con, v, n, first=(i == 0))


def main() -> None:
    signals, views = load_config()
    with duckdb.connect(str(DB_PATH)) as con:
        scores = score(con.execute("SELECT * FROM sites").df(), signals, views)
        write_scores(con, scores, views)
        print(f"Scored {len(scores)} sites; {scores['score_missing'].notna().sum()} scored on partial signals.")
        print_all_tops(con, views)


if __name__ == "__main__":
    main()
