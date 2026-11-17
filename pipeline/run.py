"""Build and score data/grid.duckdb in one command.

Usage:
    uv run python -m pipeline.run              # download missing raw data, then build
    uv run python -m pipeline.run --refresh    # re-download everything first
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from .adapters.base import DNOAdapter
from .adapters.ukpn import UKPNAdapter
from .normalise import build_all
from .score import load_signals, print_top, score, write_scores

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grid.duckdb"

ADAPTERS: list[DNOAdapter] = [UKPNAdapter()]


def build(adapters: list[DNOAdapter], db_path: Path = DB_PATH, refresh: bool = False) -> dict[str, pd.DataFrame]:
    tables: dict[str, list[pd.DataFrame]] = {}
    for adapter in adapters:
        adapter.download(refresh=refresh)
        for name, df in build_all(adapter).items():
            tables.setdefault(name, []).append(df)
    combined = {name: pd.concat(dfs, ignore_index=True) for name, dfs in tables.items()}

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        for name, df in combined.items():
            con.register("_df", df)
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
            con.unregister("_df")
        signals = load_signals()
        write_scores(con, score(combined["sites"], signals), signals)
    return combined


def summary(tables: dict[str, pd.DataFrame]) -> None:
    sites = tables["sites"]
    print(f"\nWrote {DB_PATH}")
    for name, df in tables.items():
        print(f"  {name:20s} {len(df):6,} rows")
    print(f"\nsites: {len(sites)} substations, {sites['scorable'].sum()} scorable")
    print("  filled per signal column:")
    for col in ["firm_capacity_mw", "demand_headroom_mw", "observed_peak_mw",
                "queue_mw", "connections_last_year", "headroom_2030_mw"]:
        print(f"    {col:24s} {sites[col].notna().sum():5d}/{len(sites)}")
    print("  queue_source:", sites["queue_source"].value_counts().to_dict())
    excluded = sites[~sites["scorable"]]
    if len(excluded):
        print("  excluded:", excluded[["site_id", "name", "exclude_reason"]].to_dict("records"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="re-download all raw datasets")
    args = parser.parse_args()
    summary(build(ADAPTERS, refresh=args.refresh))
    print("\nTop 20 by stuck-demand score:")
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        print_top(con)


if __name__ == "__main__":
    main()
