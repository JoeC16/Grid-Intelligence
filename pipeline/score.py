"""Stuck-demand score, 0-100, for each scorable site.

Usage:  uv run python -m pipeline.score     # score data/grid.duckdb, print top 20

Method (see config/weights.yaml):
  1. Derive utilisation = observed_peak_mw / firm_capacity_mw.
  2. Percentile-rank each signal across scorable sites, oriented so 1 = most
     stuck. Ties share the lowest rank, so e.g. every zero-queue site gets 0.
  3. Weighted sum of the percentiles a site has, divided by the weights of
     those signals, times 100. Missing signals are listed in score_missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
WEIGHTS_PATH = ROOT / "config" / "weights.yaml"
DB_PATH = ROOT / "data" / "grid.duckdb"


@dataclass(frozen=True)
class Signal:
    key: str
    weight: float
    column: str
    direction: str  # "high" or "low"
    label: str


def load_signals(path: Path = WEIGHTS_PATH) -> list[Signal]:
    raw = yaml.safe_load(path.read_text())["signals"]
    signals = [
        Signal(key, float(s["weight"]), s["column"], s["direction"], s.get("label", key))
        for key, s in raw.items()
    ]
    for s in signals:
        if s.direction not in ("high", "low"):
            raise ValueError(f"{s.key}: direction must be 'high' or 'low', got {s.direction!r}")
        if s.weight < 0:
            raise ValueError(f"{s.key}: weight must be >= 0")
    return signals


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


def score(sites: pd.DataFrame, signals: list[Signal]) -> pd.DataFrame:
    """Return site_id, raw signal values, pct_<signal>, score, rank, score_missing."""
    df = add_derived(sites)
    df = df[df["scorable"]].copy()

    pct_cols = []
    for s in signals:
        col = f"pct_{s.key}"
        df[col] = percentile(df[s.column], s.direction)
        pct_cols.append(col)

    weights = pd.Series({f"pct_{s.key}": s.weight for s in signals})
    present = df[pct_cols].notna()
    weighted = df[pct_cols].fillna(0).mul(weights).sum(axis=1)
    available = present.mul(weights).sum(axis=1)
    df["score"] = (100 * weighted / available.where(available > 0)).round(1)
    df["signals_used"] = present.sum(axis=1)
    df["score_missing"] = present.apply(
        lambda row: ",".join(s.key for s in signals if not row[f"pct_{s.key}"]) or None, axis=1
    )
    df["rank"] = df["score"].rank(ascending=False, method="min").astype("Int64")

    raw_cols = list(dict.fromkeys(s.column for s in signals))
    keep = ["site_id", "score", "rank", "signals_used", "score_missing", *pct_cols, *raw_cols]
    return df[keep].sort_values(["rank", "site_id"]).reset_index(drop=True)


def write_scores(con: duckdb.DuckDBPyConnection, scores: pd.DataFrame, signals: list[Signal]) -> None:
    con.register("_scores", scores)
    con.execute("CREATE OR REPLACE TABLE site_scores AS SELECT * FROM _scores")
    con.unregister("_scores")
    weights = pd.DataFrame([s.__dict__ for s in signals])
    con.register("_w", weights)
    con.execute("CREATE OR REPLACE TABLE score_weights AS SELECT * FROM _w")
    con.unregister("_w")


def print_top(con: duckdb.DuckDBPyConnection, n: int = 20) -> None:
    top = con.execute(
        f"""
        SELECT s.rank, s.score, t.name, t.licence_area AS area, t.gsp,
               round(t.queue_mw, 1) AS queue_mw,
               round(t.demand_headroom_mw, 1) AS headroom_mw,
               round(s.utilisation * 100) AS util_pct,
               t.connections_last_year AS accepted_1y,
               round(t.headroom_2030_mw, 1) AS headroom_2030_mw,
               s.score_missing
        FROM site_scores s JOIN sites t USING (site_id)
        ORDER BY s.rank, t.site_id
        LIMIT {int(n)}
        """
    ).df()
    with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 38):
        print(top.to_string(index=False))


def main() -> None:
    signals = load_signals()
    with duckdb.connect(str(DB_PATH)) as con:
        scores = score(con.execute("SELECT * FROM sites").df(), signals)
        write_scores(con, scores, signals)
        print(f"Scored {len(scores)} sites; {scores['score_missing'].notna().sum()} scored on partial signals.\n")
        print_top(con)


if __name__ == "__main__":
    main()
