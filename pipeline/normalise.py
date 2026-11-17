"""Turn adapter outputs into the common schema. DNO-agnostic.

Tables produced:
  sites               one row per scorable substation
  headroom_scenarios  long table of forecast headroom (all scenarios, all years)
  gsps                primaries rolled up to their GSP, plus the large demand list
  large_demand        large committed demand projects (GSP level)
  field_sources       field -> dataset ID, publish date, URL
"""

from __future__ import annotations

import re

import pandas as pd

from .adapters.base import (
    FUTURE_HEADROOM_COLUMNS,
    GSP_QUEUE_COLUMNS,
    HEADROOM_COLUMNS,
    LARGE_DEMAND_COLUMNS,
    QUEUE_COLUMNS,
    SITES_COLUMNS,
    DNOAdapter,
)

HEADROOM_YEAR = 2030

# Columns the scorer uses. Nulls here are listed in missing_signals.
SIGNAL_COLUMNS = [
    "firm_capacity_mw",
    "demand_headroom_mw",
    "observed_peak_mw",
    "queue_mw",
    "connections_last_year",
    "headroom_2030_mw",
]

SITE_COLUMNS = [
    "site_id", "dno", "name", "lat", "lon", "voltage", "licence_area", "gsp",
    "firm_capacity_mw", "demand_headroom_mw", "observed_peak_mw",
    "queue_mw", "queue_source", "connections_last_year", "headroom_2030_mw",
]  # + headroom_2030_<scenario> columns, then flags and sources


def scenario_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _check(df: pd.DataFrame, cols: list[str], what: str) -> pd.DataFrame:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{what} is missing columns: {missing}")
    return df[cols]


def headroom_by_scenario(future: pd.DataFrame, year: int = HEADROOM_YEAR) -> pd.DataFrame:
    """Wide table: site_id + headroom_<year>_<scenario> for each scenario."""
    sel = future[future["year"] == year]
    wide = sel.pivot_table(index="site_id", columns="scenario", values="headroom_mw", aggfunc="sum")
    wide.columns = [f"headroom_{year}_{scenario_slug(c)}" for c in wide.columns]
    return wide.reset_index()


def build_sites(adapter: DNOAdapter) -> pd.DataFrame:
    sites = _check(adapter.fetch_sites(), SITES_COLUMNS, "fetch_sites")
    if sites["site_id"].duplicated().any():
        dups = sites.loc[sites["site_id"].duplicated(), "site_id"].tolist()
        raise ValueError(f"fetch_sites returned duplicate site_ids: {dups[:5]}")
    headroom = _check(adapter.fetch_headroom(), HEADROOM_COLUMNS, "fetch_headroom")
    queue = _check(adapter.fetch_queue(), QUEUE_COLUMNS, "fetch_queue")
    future = _check(adapter.fetch_future_headroom(), FUTURE_HEADROOM_COLUMNS, "fetch_future_headroom")
    wide = headroom_by_scenario(future)

    df = (
        sites.merge(headroom, on="site_id", how="left")
        .merge(queue, on="site_id", how="left")
        .merge(wide, on="site_id", how="left")
    )
    default_col = f"headroom_{HEADROOM_YEAR}_{scenario_slug(adapter.default_scenario)}"
    df["headroom_2030_mw"] = df[default_col] if default_col in df else pd.NA
    df["headroom_2030_scenario"] = adapter.default_scenario
    df["dno"] = adapter.dno
    df = df.rename(columns={"voltage_kv": "voltage"})

    df["missing_signals"] = df[SIGNAL_COLUMNS].isna().apply(
        lambda row: ",".join(c for c, miss in row.items() if miss) or None, axis=1
    )
    df["scorable"] = df["exclude_reason"].isna()

    record = adapter.sources()["demand_headroom_mw"]
    df["source_dataset"] = record.dataset_id
    df["source_date"] = record.publish_date

    scenario_cols = sorted(c for c in wide.columns if c != "site_id")
    tail = ["headroom_2030_scenario", "gsp_mapped", "scorable", "exclude_reason",
            "missing_signals", "source_dataset", "source_date"]
    return df[SITE_COLUMNS + scenario_cols + tail].sort_values("site_id").reset_index(drop=True)


def build_headroom_scenarios(adapter: DNOAdapter) -> pd.DataFrame:
    future = _check(adapter.fetch_future_headroom(), FUTURE_HEADROOM_COLUMNS, "fetch_future_headroom")
    return future.assign(dno=adapter.dno)[["dno", *FUTURE_HEADROOM_COLUMNS]]


def build_large_demand(adapter: DNOAdapter) -> pd.DataFrame:
    ld = _check(adapter.fetch_large_demand(), LARGE_DEMAND_COLUMNS, "fetch_large_demand")
    return ld.assign(dno=adapter.dno)[["dno", *LARGE_DEMAND_COLUMNS]]


def build_gsps(
    sites: pd.DataFrame, gsp_list: pd.DataFrame, gsp_queue: pd.DataFrame, large_demand: pd.DataFrame
) -> pd.DataFrame:
    """Roll mapped sites up to their GSP; add grid-level queue and large demand totals."""
    mapped = sites[sites["gsp_mapped"]]
    rollup = mapped.groupby("gsp").agg(
        site_count=("site_id", "count"),
        primary_queue_mw=("queue_mw", "sum"),
        demand_headroom_mw=("demand_headroom_mw", "sum"),
        connections_last_year=("connections_last_year", "sum"),
        headroom_2030_mw=("headroom_2030_mw", "sum"),
    )

    ld = large_demand.assign(
        is_large=large_demand["technology"].eq("large_demand"),
        is_der=large_demand["technology"].eq("der"),
    )
    ld_rollup = ld.groupby("gsp").agg(
        large_demand_count=("is_large", "sum"),
        large_demand_mva=("import_capacity_mva", lambda s: s[ld.loc[s.index, "is_large"]].sum()),
        der_import_count=("is_der", "sum"),
        der_import_mva=("import_capacity_mva", lambda s: s[ld.loc[s.index, "is_der"]].sum()),
    )

    grid_queue = gsp_queue.groupby("gsp")["queue_mw"].sum().rename("grid_level_queue_mw")

    gsps = (
        gsp_list.set_index("gsp")
        .join(rollup, how="outer")
        .join(grid_queue, how="outer")
        .join(ld_rollup, how="outer")
    )
    gsps["in_gsp_list"] = gsps.index.isin(gsp_list["gsp"])
    for col in ["site_count", "large_demand_count", "der_import_count", "connections_last_year"]:
        gsps[col] = gsps[col].fillna(0).astype(int)
    for col in ["primary_queue_mw", "grid_level_queue_mw", "large_demand_mva", "der_import_mva"]:
        gsps[col] = gsps[col].fillna(0.0)
    gsps["queue_mw"] = gsps["primary_queue_mw"] + gsps["grid_level_queue_mw"]
    return gsps.reset_index().rename(columns={"index": "gsp"}).sort_values("gsp").reset_index(drop=True)


def build_field_sources(adapter: DNOAdapter) -> pd.DataFrame:
    rows = [
        {"dno": adapter.dno, "field": f, "dataset_id": s.dataset_id, "publish_date": s.publish_date, "url": s.url}
        for f, s in adapter.sources().items()
    ]
    return pd.DataFrame(rows)


def build_all(adapter: DNOAdapter) -> dict[str, pd.DataFrame]:
    sites = build_sites(adapter)
    large_demand = build_large_demand(adapter)
    gsp_queue = _check(adapter.fetch_gsp_queue(), GSP_QUEUE_COLUMNS, "fetch_gsp_queue")
    gsps = build_gsps(sites, adapter.fetch_gsps(), gsp_queue, large_demand).assign(dno=adapter.dno)
    return {
        "sites": sites,
        "headroom_scenarios": build_headroom_scenarios(adapter),
        "gsps": gsps,
        "large_demand": large_demand,
        "field_sources": build_field_sources(adapter),
    }
