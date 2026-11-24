"""Build and score data/grid.duckdb in one command.

Usage:
    uv run python -m pipeline.run              # download missing raw data, then build
    uv run python -m pipeline.run --refresh    # take a new bronze snapshot (re-download everything) first
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from .adapters.base import DNOAdapter
from .adapters.ukpn import UKPNAdapter
from . import checks, medallion
from .normalise import build_all
from .score import load_config, print_all_tops, score, write_scores

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grid.duckdb"

ADAPTERS: list[DNOAdapter] = [UKPNAdapter()]


def _write(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> None:
    con.register("_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _df")
    con.unregister("_df")


def _silver_for(adapter: DNOAdapter, signals, views) -> list[dict[str, pd.DataFrame]]:
    """Silver rows for every bronze snapshot this adapter has."""
    out = []
    for day in adapter.snapshot_dates():
        a = adapter if day == adapter.snapshot_date else adapter.for_snapshot(day)
        try:
            t = build_all(a)
        except (FileNotFoundError, KeyError) as exc:  # an incomplete old snapshot
            print(f"  skipping snapshot {day}: {type(exc).__name__}: {exc}")
            continue
        out.append(medallion.silver_snapshot(t, score(t["sites"], signals, views), day))
    return out


def build(adapters: list[DNOAdapter], db_path: Path = DB_PATH, refresh: bool = False) -> dict[str, pd.DataFrame]:
    signals, views = load_config()
    tables: dict[str, list[pd.DataFrame]] = {}
    silver_parts: list[dict[str, pd.DataFrame]] = []
    for adapter in adapters:
        adapter.download(refresh=refresh)
        for name, df in build_all(adapter).items():
            tables.setdefault(name, []).append(df)
        silver_parts += _silver_for(adapter, signals, views)
    combined = {name: pd.concat(dfs, ignore_index=True) for name, dfs in tables.items()}
    scores = score(combined["sites"], signals, views)
    silver = {k: pd.concat([p[k] for p in silver_parts], ignore_index=True) for k in ("sites", "bsps", "gsps")}
    silver["nodes"] = medallion.graph_nodes(combined, combined["field_sources"])
    silver["edges"] = combined["edges"]
    latest = adapters[0].snapshot_date
    from_year = int(latest[:4]) if latest[:4].isdigit() else pd.Timestamp.now().year
    gold = medallion.build_gold(combined, scores, silver, adapters[0].default_scenario, from_year)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path)) as con:
        # Current tables the app reads (gold, unqualified names).
        for name, df in combined.items():
            _write(con, name, df)
        write_scores(con, scores, views)
        con.execute("CREATE SCHEMA IF NOT EXISTS silver")
        con.execute("CREATE SCHEMA IF NOT EXISTS gold")
        for name, df in silver.items():
            _write(con, f"silver.{name}", df)
        for name, df in gold.items():
            _write(con, f"gold.{name}", df)
    combined["_silver_snapshots"] = pd.DataFrame({"snapshot_date": sorted(silver["sites"]["snapshot_date"].unique())})
    combined.update({f"gold.{k}": v for k, v in gold.items()})
    return combined


def summary(tables: dict[str, pd.DataFrame]) -> None:
    sites = tables["sites"]
    print(f"\nWrote {DB_PATH}")
    snaps = tables.pop("_silver_snapshots")["snapshot_date"].tolist()
    print(f"  bronze snapshots in silver: {snaps}")
    for name, df in tables.items():
        print(f"  {name:28s} {len(df):6,} rows")
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
    _, views = load_config()
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        print_all_tops(con, views)
    print("\nData quality checks:")
    if not checks.report(checks.run()):
        raise SystemExit("Data quality checks failed: don't deploy this build (see docs/OPERATIONS.md).")


if __name__ == "__main__":
    main()
