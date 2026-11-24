"""Network graph: GSP → BSP → primary, and constraints flowing down it. DNO-agnostic.

Inputs come from the adapter (fetch_topology, fetch_gsps) and the sites table.
For each site it adds:

  bsp_id, bsp_name             the bulk supply point it hangs off (None = fed directly from the GSP)
  bsp_headroom_mw              published headroom at that BSP
  bsp_queue_mw                 demand queued at every site under that BSP (the BSP's own board included)
  bsp_headroom_after_queue_mw  bsp_headroom_mw − bsp_queue_mw
  effective_headroom_mw        min(site headroom after queue, BSP headroom after queue)
  limiting_level               "primary", "bsp", or "primary (BSP not published)"
  upstream_constrained         the BSP is the tighter limit
  gsp_over_capacity            the GSP's published import utilisation (peak / capacity) is 100% or more

GSPs have no MW headroom figure, so they raise a flag rather than set a limit.
(The GSP overview's technical-limits RAG says whether limits have been agreed
with the system operator yet; it is not a constraint signal and isn't used here.)
"""

from __future__ import annotations

import pandas as pd

UPSTREAM_COLUMNS = [
    "bsp_id", "bsp_name", "bsp_headroom_mw", "bsp_queue_mw", "bsp_headroom_after_queue_mw",
    "effective_headroom_mw", "limiting_level", "upstream_constrained", "gsp_over_capacity",
]


def build(sites: pd.DataFrame, bsps: pd.DataFrame, links: pd.DataFrame, gsps: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Return {"sites": sites + UPSTREAM_COLUMNS, "bsps": BSP roll-up, "edges": child→parent}."""
    s = sites.drop(columns=[c for c in UPSTREAM_COLUMNS if c in sites.columns]).merge(links, on="site_id", how="left")
    s["headroom_after_queue_mw"] = s["demand_headroom_mw"] - s["queue_mw"]
    s["_stuck_mw"] = (s["queue_mw"] - s["demand_headroom_mw"]).clip(lower=0)

    # Roll up to BSPs: queue under each BSP, and stuck demand at BSP level.
    under = s.dropna(subset=["bsp_id"]).groupby("bsp_id").agg(
        site_count=("site_id", "count"),
        queue_mw=("queue_mw", "sum"),
        children_stuck_mw=("_stuck_mw", "sum"),
    )
    b = bsps.set_index("bsp_id").join(under, how="left")
    b["site_count"] = b["site_count"].fillna(0).astype(int)
    b["queue_mw"] = b["queue_mw"].fillna(0.0)
    b["headroom_after_queue_mw"] = b["headroom_mw"] - b["queue_mw"]
    # Queued demand the BSP itself can't absorb (NaN where its headroom isn't published).
    b["stuck_mw"] = (b["queue_mw"] - b["headroom_mw"]).clip(lower=0)

    # Per-site upstream view.
    s = s.join(b[["name", "headroom_mw", "queue_mw", "headroom_after_queue_mw"]].rename(columns={
        "name": "bsp_name", "headroom_mw": "bsp_headroom_mw", "queue_mw": "bsp_queue_mw",
        "headroom_after_queue_mw": "bsp_headroom_after_queue_mw"}), on="bsp_id")
    local, upstream = s["headroom_after_queue_mw"], s["bsp_headroom_after_queue_mw"]
    s["effective_headroom_mw"] = pd.concat([local, upstream], axis=1).min(axis=1, skipna=True).where(local.notna())
    s["upstream_constrained"] = upstream.notna() & local.notna() & (upstream < local)
    s["limiting_level"] = "primary"
    s.loc[s["upstream_constrained"], "limiting_level"] = "bsp"
    s.loc[s["bsp_id"].notna() & upstream.isna(), "limiting_level"] = "primary (BSP not published)"
    s.loc[local.isna(), "limiting_level"] = None

    util = gsps.get("import_capacity_utilisation_pct", pd.Series(dtype=float))
    over = set(gsps.loc[util >= 100, "gsp"]) if len(gsps) else set()
    s["gsp_over_capacity"] = s["gsp"].isin(over)
    s = s.drop(columns=["headroom_after_queue_mw", "_stuck_mw"])

    # Edges: site → its BSP (or straight to its GSP); a BSP's own board → the GSP; BSP → GSP.
    own_board = set(b["site_id"].dropna())
    edges = []
    for r in s[["site_id", "bsp_id", "gsp"]].itertuples(index=False):
        if pd.notna(r.bsp_id) and r.site_id not in own_board:
            parent = r.bsp_id
        elif pd.notna(r.gsp):
            parent = f"GSP:{r.gsp}"
        else:
            continue  # no BSP and no mapped GSP
        edges.append({"child_id": r.site_id, "parent_id": parent, "kind": "site"})
    for bsp_id, r in b.iterrows():
        if pd.notna(r["gsp"]):
            edges.append({"child_id": bsp_id, "parent_id": f"GSP:{r['gsp']}", "kind": "bsp"})

    optional = [c for c in ("cep_mw", "occupied_mw", "admitted_mw", "free_bays") if c in b.columns]
    bsp_out = b.reset_index()[[
        "bsp_id", "name", "licence_area", "lat", "lon", "site_id", "gsp", "matched", "note",
        "headroom_mw", "headroom_source", "site_count", "queue_mw", "headroom_after_queue_mw",
        "stuck_mw", "children_stuck_mw", *optional,
    ]]
    bsp_out["stuck_rank"] = (
        bsp_out["stuck_mw"].where(bsp_out["stuck_mw"] > 0).round(3).rank(ascending=False, method="min").astype("Int64")
    )
    return {"sites": s, "bsps": bsp_out.sort_values("bsp_id").reset_index(drop=True), "edges": pd.DataFrame(edges)}
