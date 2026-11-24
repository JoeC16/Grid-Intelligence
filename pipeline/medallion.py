"""Silver and gold layers (Phase 10). DNO-agnostic. See docs/DATA_MODEL.md.

Silver: conformed entities, one row per entity per snapshot, plus the graph.
Gold:   marts per level (GSP, BSP, site) with the same core measures, time
        series, and changes between snapshots.

Bronze (raw files per snapshot) lives in pipeline/bronze.py.
"""

from __future__ import annotations

import pandas as pd

from . import unlock

# Columns kept per snapshot in silver (enough to diff and to rebuild any mart).
SILVER_SITE_COLUMNS = [
    "site_id", "dno", "country", "operator", "capacity_taken_mw", "name", "licence_area", "voltage", "gsp", "bsp_id", "lat", "lon",
    "firm_capacity_mw", "demand_headroom_mw", "observed_peak_mw", "queue_mw", "connections_last_year",
    "headroom_2030_mw", "effective_headroom_mw", "limiting_level", "scorable",
    "score", "rank", "stuck_mw", "stuck_rank",
]
SILVER_BSP_COLUMNS = ["bsp_id", "dno", "name", "licence_area", "gsp", "site_id", "matched", "site_count",
                      "headroom_mw", "queue_mw", "headroom_after_queue_mw", "stuck_mw", "stuck_rank"]
SILVER_GSP_COLUMNS = ["gsp", "dno", "licence_area", "site_count", "queue_mw", "primary_queue_mw",
                      "grid_level_queue_mw", "large_demand_count", "large_demand_mva",
                      "import_capacity_utilisation_pct", "technical_limit_rag"]


# ------------------------------------------------------------------ silver --


def silver_snapshot(tables: dict[str, pd.DataFrame], scores: pd.DataFrame, snapshot_date: str) -> dict[str, pd.DataFrame]:
    """One snapshot's conformed entities, each row stamped with snapshot_date."""
    sites = tables["sites"].merge(
        scores[["site_id", "score", "rank", "stuck_mw", "stuck_rank"]], on="site_id", how="left")
    out = {
        "sites": sites.reindex(columns=SILVER_SITE_COLUMNS),
        "bsps": tables["bsps"].reindex(columns=SILVER_BSP_COLUMNS),
        "gsps": tables["gsps"].reindex(columns=SILVER_GSP_COLUMNS),
    }
    return {k: v.assign(snapshot_date=snapshot_date) for k, v in out.items()}


def graph_nodes(tables: dict[str, pd.DataFrame], sources: pd.DataFrame) -> pd.DataFrame:
    """Every node of the network graph (GSP, BSP, site) with location and the dataset it comes from."""
    src = dict(zip(sources["field"], sources["dataset_id"]))
    s, b, g = tables["sites"], tables["bsps"], tables["gsps"]
    g = g[g["lat"].notna()] if "lat" in g else g.iloc[0:0]
    return pd.concat([
        pd.DataFrame({"node_id": "GSP:" + g["gsp"], "level": "gsp", "name": g["gsp"], "dno": g["dno"],
                      "licence_area": g["licence_area"], "lat": g["lat"], "lon": g["lon"],
                      "source_dataset": src.get("gsp")}),
        pd.DataFrame({"node_id": b["bsp_id"], "level": "bsp", "name": b["name"], "dno": b["dno"],
                      "licence_area": b["licence_area"], "lat": b["lat"], "lon": b["lon"],
                      "source_dataset": b["headroom_source"].fillna(src.get("name"))}),
        pd.DataFrame({"node_id": s["site_id"], "level": "site", "name": s["name"], "dno": s["dno"],
                      "licence_area": s["licence_area"], "lat": s["lat"], "lon": s["lon"],
                      "source_dataset": src.get("name")}),
    ], ignore_index=True)


# -------------------------------------------------------------------- gold --


def runs_out_year(headroom_scenarios: pd.DataFrame, scenario: str, from_year: int) -> pd.Series:
    """Per site: the first forecast year from `from_year` on with published headroom below zero.

    NaN = stays at or above zero through the last forecast year.
    """
    h = headroom_scenarios[(headroom_scenarios["scenario"] == scenario) & (headroom_scenarios["year"] >= from_year)]
    neg = h[h["headroom_mw"] < 0]
    return neg.groupby("site_id")["year"].min()


def site_mart(sites: pd.DataFrame, scores: pd.DataFrame, run_out: pd.Series) -> pd.DataFrame:
    m = sites.merge(scores[["site_id", "score", "rank", "stuck_mw", "stuck_rank", "utilisation"]], on="site_id", how="left")
    m["runs_out_year"] = m["site_id"].map(run_out).astype("Int64")
    cols = ["site_id", "dno", "country", "operator", "operator_name", "province", "municipality",
            "name", "licence_area", "voltage", "gsp", "bsp_id", "bsp_name", "lat", "lon", "capacity_taken_mw",
            "scorable", "score", "rank", "demand_headroom_mw", "queue_mw", "stuck_mw", "stuck_rank",
            "effective_headroom_mw", "limiting_level", "headroom_2030_mw", "runs_out_year", "utilisation"]
    return m[cols]


def bsp_mart(bsps: pd.DataFrame, smart: pd.DataFrame) -> pd.DataFrame:
    scorable = smart[smart["scorable"]]
    per = scorable.groupby("bsp_id").agg(
        sites_limited_by_bsp=("limiting_level", lambda x: int((x == "bsp").sum())),
        earliest_runs_out_year=("runs_out_year", "min"),
    )
    # The BSP's own runs-out year is its own board's, where it has one.
    own = smart.set_index("site_id")["runs_out_year"]
    m = bsps.set_index("bsp_id").join(per, how="left")
    m["runs_out_year"] = m["site_id"].map(own).astype("Int64")
    m["sites_limited_by_bsp"] = m["sites_limited_by_bsp"].fillna(0).astype(int)
    m["earliest_runs_out_year"] = m["earliest_runs_out_year"].astype("Int64")
    return m.reset_index()


def gsp_mart(gsps: pd.DataFrame, bmart: pd.DataFrame, smart: pd.DataFrame, by: int) -> pd.DataFrame:
    """GSP level: the same core measures, rolled up from BSPs and sites."""
    s = smart[smart["scorable"]]
    direct = s[s["bsp_id"].isna()]
    per_site = s.groupby("gsp").agg(
        sites_limited_by_bsp=("limiting_level", lambda x: int((x == "bsp").sum())),
        sites_running_out_by=("runs_out_year", lambda x: int((x <= by).sum())),
        earliest_runs_out_year=("runs_out_year", "min"),
    )
    bsp_stuck = bmart.groupby("gsp").agg(bsp_count=("bsp_id", "count"), bsp_stuck_mw=("stuck_mw", "sum"))
    direct_stuck = direct.groupby("gsp")["stuck_mw"].sum().rename("direct_site_stuck_mw")
    m = gsps.set_index("gsp").join(per_site, how="left").join(bsp_stuck, how="left").join(direct_stuck, how="left")
    for c in ["sites_limited_by_bsp", "sites_running_out_by", "bsp_count"]:
        m[c] = m[c].fillna(0).astype(int)
    m["bsp_stuck_mw"] = m["bsp_stuck_mw"].fillna(0.0)
    m["direct_site_stuck_mw"] = m["direct_site_stuck_mw"].fillna(0.0)
    # Stuck demand under the GSP: at its BSPs, plus at sites fed directly from it.
    m["stuck_mw"] = m["bsp_stuck_mw"] + m["direct_site_stuck_mw"]
    m["earliest_runs_out_year"] = m["earliest_runs_out_year"].astype("Int64")
    m["running_out_by_year"] = by
    out = m.reset_index().rename(columns={"index": "gsp"})
    out["stuck_rank"] = out["stuck_mw"].where(out["stuck_mw"] > 0).round(3).rank(ascending=False, method="min").astype("Int64")
    return out


def headroom_timeline(headroom_scenarios: pd.DataFrame, smart: pd.DataFrame) -> pd.DataFrame:
    """Per scenario and forecast year: scorable sites with negative published headroom, and the total."""
    ids = set(smart.loc[smart["scorable"], "site_id"])
    h = headroom_scenarios[headroom_scenarios["site_id"].isin(ids)]
    return h.groupby(["scenario", "year"]).agg(
        sites=("site_id", "nunique"),
        sites_negative=("headroom_mw", lambda x: int((x < 0).sum())),
        total_headroom_mw=("headroom_mw", "sum"),
    ).reset_index()


def large_demand_by_year(large_demand: pd.DataFrame) -> pd.DataFrame:
    ld = large_demand.assign(year=pd.to_datetime(large_demand["application_date"]).dt.year)
    return ld.groupby(["dno", "gsp", "technology", "year"]).agg(
        projects=("project_id", "count"), import_capacity_mva=("import_capacity_mva", "sum")).reset_index()


CHANGE_COLUMNS = ["dno", "level", "id", "name", "measure", "previous", "latest", "change",
                  "previous_snapshot", "latest_snapshot"]


def changes(silver_sites: pd.DataFrame, silver_bsps: pd.DataFrame) -> pd.DataFrame:
    """Latest vs previous snapshot, per DNO (each keeps its own snapshot dates)."""
    parts = [_changes_one(silver_sites[silver_sites["dno"] == d], silver_bsps[silver_bsps["dno"] == d]).assign(dno=d)
             for d in sorted(silver_sites["dno"].dropna().unique())]
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True)[CHANGE_COLUMNS] if parts else pd.DataFrame(columns=CHANGE_COLUMNS)


def _changes_one(silver_sites: pd.DataFrame, silver_bsps: pd.DataFrame) -> pd.DataFrame:
    """Latest vs previous snapshot: what moved, per site and per BSP. Empty with one snapshot."""
    dates = sorted(silver_sites["snapshot_date"].unique())
    cols = ["level", "id", "name", "measure", "previous", "latest", "change", "previous_snapshot", "latest_snapshot"]
    if len(dates) < 2:
        return pd.DataFrame(columns=cols)
    prev, last = dates[-2], dates[-1]
    rows = []
    for level, df, key, measures in [
        ("site", silver_sites, "site_id", ["queue_mw", "demand_headroom_mw", "effective_headroom_mw", "stuck_mw", "score"]),
        ("bsp", silver_bsps, "bsp_id", ["queue_mw", "headroom_mw", "stuck_mw"]),
    ]:
        a = df[df["snapshot_date"] == prev].set_index(key)
        b = df[df["snapshot_date"] == last].set_index(key)
        common = a.index.intersection(b.index)
        for m in measures:
            delta = (b.loc[common, m] - a.loc[common, m]).round(3)
            moved = delta[delta.abs() > 0.05]
            for i, d in moved.items():
                rows.append({"level": level, "id": i, "name": b.at[i, "name"], "measure": m,
                             "previous": a.at[i, m], "latest": b.at[i, m], "change": d,
                             "previous_snapshot": prev, "latest_snapshot": last})
    return pd.DataFrame(rows, columns=cols)


def operator_mart(sites: pd.DataFrame, scores: pd.DataFrame) -> pd.DataFrame:
    """One row per distribution network operator: the "which networks to buy or expand" view.

    Busbars/sites published, how many have no published headroom left, MW of published
    headroom, MW queued, MW stuck (queue beyond headroom, summed over sites), MW already
    taken, and the operator's most stuck site. Sums are indicative: the CNMC notes that
    capacities at neighbouring nodes affect each other, so they aren't strictly additive.
    """
    s = sites.merge(scores[["site_id", "score", "stuck_mw"]], on="site_id", how="left")
    s["stuck_mw"] = s["stuck_mw"].fillna((s["queue_mw"] - s["demand_headroom_mw"]).clip(lower=0))
    s["_zero"] = s["demand_headroom_mw"] <= 0
    g = s.groupby(["country", "dno", "operator"], dropna=False)
    m = g.agg(
        operator_name=("operator_name", "first"),
        licence_area=("licence_area", "first"),
        sites=("site_id", "count"),
        scored_sites=("score", "count"),
        substations=("name", lambda x: x.str.replace(r" [\d.]+ kV.*$", "", regex=True).nunique()),
        provinces=("province", lambda x: ", ".join(sorted(x.dropna().astype(str).unique())[:6])),
        province_count=("province", "nunique"),
        sites_zero_headroom=("_zero", "sum"),
        headroom_mw=("demand_headroom_mw", "sum"),
        queue_mw=("queue_mw", "sum"),
        stuck_mw=("stuck_mw", "sum"),
        capacity_taken_mw=("capacity_taken_mw", "sum"),
        median_score=("score", "median"),
    ).reset_index()
    m["share_zero_headroom"] = m["sites_zero_headroom"] / m["sites"]
    top = s[s["stuck_mw"] > 0].sort_values("stuck_mw", ascending=False).drop_duplicates(["country", "operator"])
    m = m.merge(top[["country", "operator", "site_id", "name", "stuck_mw"]].rename(
        columns={"site_id": "top_site_id", "name": "top_site_name", "stuck_mw": "top_site_stuck_mw"}),
        on=["country", "operator"], how="left")
    m["capacity_taken_mw"] = m["capacity_taken_mw"].where(m["capacity_taken_mw"] > 0)
    # Rank within each country by MW stuck (sites with any stuck demand only).
    m["stuck_rank"] = m.groupby("country")["stuck_mw"].transform(
        lambda x: x.where(x > 0).round(3).rank(ascending=False, method="min")).astype("Int64")
    return m.sort_values(["country", "stuck_mw"], ascending=[True, False]).reset_index(drop=True)


def build_gold(tables: dict[str, pd.DataFrame], scores: pd.DataFrame, silver: dict[str, pd.DataFrame],
               scenario: str, from_year: int, running_out_by: int = 2030) -> dict[str, pd.DataFrame]:
    run_out = runs_out_year(tables["headroom_scenarios"], scenario, from_year)
    smart = site_mart(tables["sites"], scores, run_out)
    bmart = bsp_mart(tables["bsps"], smart)
    return {
        "site_mart": smart,
        "bsp_mart": bmart,
        "gsp_mart": gsp_mart(tables["gsps"], bmart, smart, running_out_by),
        "headroom_timeline": headroom_timeline(tables["headroom_scenarios"], smart),
        "large_demand_by_year": large_demand_by_year(tables["large_demand"]),
        "changes": changes(silver["sites"], silver["bsps"]),
        "operator_mart": operator_mart(tables["sites"], scores),
        **dict(zip(("unlock_mart", "unlock_curve"), unlock.build(tables["sites"], tables["bsps"]))),
    }
