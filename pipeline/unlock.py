"""Unlock planner (Phase 15): where added capacity unlocks the most demand. DNO-agnostic.

For every upper-level node with published headroom (a GB BSP, a Spanish
transmission node) and the sites under it, adding A MW at the node gives:

  node after queue   U(A) = H + A − Q          H = node published headroom, Q = queue under it
  queue served       min(A, max(Q − N − H, 0)) queued demand that was waiting only on the node
                                               (N = needs_local: queue beyond a site's *own*
                                               headroom, which also needs a local upgrade)
  … with local work  min(A, max(Q − H, 0))     the same if those sites were upgraded too
  new capacity       min(spare, max(U(A), 0))  room for *new* demand once the queue is served,
                                               capped by the spare published headroom at the sites
                                               (spare = Σ max(site headroom − site queue, 0))
  sites open (L)     sites with min(site after its queue, U(A)) ≥ L

Rankings use the *gain* from adding A MW (value at A minus value at 0), so a node
that already has room doesn't rank as a good place to add more. Shared node
capacity is never double-counted: new capacity is the lower of the sites' spare
and what is left at the node. All queued demand counts as ahead of new demand. A screening tool, not an engineering study: published headroom is
indicative, there is no power-flow model, and no reinforcement costs are
published (the UKPN heatmap's "budget estimates" are quotes given, not £).
"""

from __future__ import annotations

import pandas as pd

STEPS = (0, 10, 25, 50, 100, 200, 350)  # MW added at the node
LOAD_MW = 10.0  # "sites open" = sites that could then take a load this size

CURVE_COLUMNS = ["bsp_id", "added_mw", "queue_served_mw", "queue_served_with_local_mw", "new_capacity_mw",
                 "unlocked_mw", "sites_open"]


def node_inputs(sites: pd.DataFrame, bsps: pd.DataFrame) -> pd.DataFrame:
    """Per node: H, Q, spare at its sites, queue needing local work, site count."""
    s = sites[sites["bsp_id"].notna()].copy()
    s["after"] = s["demand_headroom_mw"] - s["queue_mw"]
    s["spare"] = s["after"].clip(lower=0)
    s["needs_local"] = (s["queue_mw"] - s["demand_headroom_mw"].clip(lower=0)).clip(lower=0)
    per = s.groupby("bsp_id").agg(spare_mw=("spare", "sum"), needs_local_mw=("needs_local", "sum"),
                                  sites=("site_id", "count"))
    b = bsps[bsps["matched"].astype(bool) & bsps["headroom_mw"].notna()].set_index("bsp_id")
    out = b[["name", "dno", "lat", "lon", "headroom_mw", "queue_mw"]].join(per, how="inner")
    out["node_stuck_mw"] = (out["queue_mw"] - out["headroom_mw"]).clip(lower=0)
    return out


def curve(h: float, q: float, after: pd.Series, steps=STEPS, load_mw: float = LOAD_MW,
          needs_local: float = 0.0) -> list[dict]:
    """The unlock curve for one node. after = each site's headroom minus its own queue."""
    spare = float(after.clip(lower=0).sum())
    stuck = max(q - h, 0.0)
    stuck_node_only = max(q - needs_local - h, 0.0)
    rows = []
    for a in steps:
        u = h + a - q
        served = min(float(a), stuck_node_only)
        new = min(spare, max(u, 0.0))
        rows.append({"added_mw": a, "queue_served_mw": served, "queue_served_with_local_mw": min(float(a), stuck),
                     "new_capacity_mw": new, "unlocked_mw": served + new,
                     "sites_open": int((after.clip(upper=u) >= load_mw).sum())})
    return rows


def mw_to_first_open(h: float, q: float, after: pd.Series, load_mw: float = LOAD_MW) -> float | None:
    """MW to add at the node before any site under it can take load_mw. None: no site has the
    local headroom for it, so it would need a local upgrade too."""
    if not (after >= load_mw).any():
        return None
    return max(0.0, q + load_mw - h)


def build(sites: pd.DataFrame, bsps: pd.DataFrame, steps=STEPS, load_mw: float = LOAD_MW) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(unlock_mart: one row per node with headline figures, unlock_curve: node × step)."""
    nodes = node_inputs(sites, bsps)
    after_by = (sites.assign(after=sites["demand_headroom_mw"] - sites["queue_mw"])
                .dropna(subset=["bsp_id"]).groupby("bsp_id")["after"])
    curves, marts = [], []
    for bsp_id, n in nodes.iterrows():
        after = after_by.get_group(bsp_id).dropna()
        c = curve(n["headroom_mw"], n["queue_mw"], after, steps, load_mw, n["needs_local_mw"])
        curves += [{"bsp_id": bsp_id, **r} for r in c]
        at = {r["added_mw"]: r for r in c}
        marts.append({
            "bsp_id": bsp_id, "dno": n["dno"], "name": n["name"], "lat": n["lat"], "lon": n["lon"],
            "sites": int(n["sites"]), "headroom_mw": n["headroom_mw"], "queue_mw": n["queue_mw"],
            "node_stuck_mw": n["node_stuck_mw"], "spare_mw": n["spare_mw"], "needs_local_mw": n["needs_local_mw"],
            "mw_to_first_open": mw_to_first_open(n["headroom_mw"], n["queue_mw"], after, load_mw),
            "new_0": at[0]["new_capacity_mw"], "open_0": at[0]["sites_open"],
            **{f"served_{a}": at[a]["queue_served_mw"] for a in steps if a},
            **{f"served_local_{a}": at[a]["queue_served_with_local_mw"] for a in steps if a},
            # gains from adding a MW (value at a minus value at 0)
            **{f"new_{a}": at[a]["new_capacity_mw"] - at[0]["new_capacity_mw"] for a in steps if a},
            **{f"open_{a}": at[a]["sites_open"] - at[0]["sites_open"] for a in steps if a},
            "load_mw": load_mw,
        })
    mart = pd.DataFrame(marts)
    if len(mart):
        # Best next moves per DNO at +50 MW. Ties (many nodes gain the full 50 MW) are broken by
        # sites opened, then by the gain at +100 MW. Nodes that gain nothing aren't ranked.
        for goal, keys in (("new", ["new_50", "open_50", "new_100"]), ("queue", ["served_50", "served_100", "open_50"])):
            keys = [k for k in keys if k in mart]
            if not keys or keys[0] not in mart:
                continue
            ranked = mart[mart[keys[0]] > 0].copy()
            ranked[keys] = ranked[keys].round(3)
            ranked = ranked.sort_values(["dno", *keys], ascending=[True] + [False] * len(keys))
            ranked[f"rank_{goal}_50"] = ranked.groupby("dno").cumcount() + 1
            mart[f"rank_{goal}_50"] = ranked[f"rank_{goal}_50"].reindex(mart.index).astype("Int64")
    return mart, pd.DataFrame(curves, columns=CURVE_COLUMNS)
