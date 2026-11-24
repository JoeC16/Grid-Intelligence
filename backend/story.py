"""The Fuse story: chapters built from the gold layer (Phase 10).

Every number in a chapter is computed here from gold / current tables at
request time; nothing is typed in by hand. Each chapter carries its sources
and a map focus the web app applies when the chapter opens.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.assistant import _num

UKPN_VIEW = {"center": [0.35, 51.55], "zoom": 7.6}


def _mw(v: float) -> str:
    """1 dp, rounded half-up like the map and the AI tools (−326.95 → −327.0)."""
    return f"{_num(v):,.1f}"


def _n(v: float) -> str:
    return f"{int(v):,}"


def build_story(data: dict[str, pd.DataFrame], source: callable, snapshot_dates: list[str]) -> dict[str, Any]:
    """data: sites, bsps, gsps, site_scores, gold_gsp_mart, gold_headroom_timeline,
    gold_large_demand_by_year, gold_changes, large_demand. source(field) -> source dict."""
    sites, gm, bsps = data["sites"], data["gold_gsp_mart"], data["bsps"]
    sc = data["site_scores"]
    tl, ldy, ch = data["gold_headroom_timeline"], data["gold_large_demand_by_year"], data["gold_changes"]
    scenario = sites["headroom_2030_scenario"].iloc[0]
    chapters: list[dict[str, Any]] = []

    # 1. The queue ------------------------------------------------------------
    total_queue = gm["queue_mw"].sum()
    grid_level = gm["grid_level_queue_mw"].sum()
    stuck_sites = sc[sc["stuck_mw"] > 0]
    stuck_bsps = bsps[bsps["stuck_mw"] > 0]
    chapters.append({
        "id": "queue",
        "title": "Demand is queuing",
        "body": (
            f"Across UK Power Networks, **{_mw(total_queue)} MW** of demand has been offered a connection and isn't "
            f"connected yet, {_mw(grid_level)} MW of it at grid level (132 kV and similar). "
            f"At **{_n(len(stuck_sites))}** primary substations the queue is already bigger than the published headroom: "
            f"**{_mw(stuck_sites['stuck_mw'].sum())} MW** of demand that the local network can't take as published. "
            f"Map: sites ranked by MW stuck."
        ),
        "facts": [
            {"label": "Demand queued", "value": total_queue, "unit": "MW"},
            {"label": "Sites with stuck demand", "value": len(stuck_sites), "unit": "sites"},
            {"label": "Stuck at those sites", "value": stuck_sites["stuck_mw"].sum(), "unit": "MW"},
        ],
        "sources": [source("queue_mw"), source("demand_headroom_mw")],
        "focus": {"view": "investor", "sort": "stuck", "network": False, **UKPN_VIEW},
    })

    # 2. Where it's stuck: GSPs and their BSPs ---------------------------------
    top = gm[gm["stuck_rank"].notna()].sort_values("stuck_rank").head(3)
    lines = [
        f"- **{r.gsp}** ({r.licence_area}): {_mw(r.stuck_mw)} MW stuck, {_mw(r.queue_mw)} MW queued across "
        f"{_n(r.bsp_count)} BSPs and {_n(r.site_count)} sites"
        for r in top.itertuples()
    ]
    first = top.iloc[0]
    chapters.append({
        "id": "where",
        "title": "Where it's stuck",
        "body": (
            f"Rolled up the network tree (grid supply point → bulk supply point → primary), stuck demand concentrates in a "
            f"few places. **{_n(len(stuck_bsps))}** bulk supply points have more demand queued under them than their "
            f"published headroom. The grid supply points with the most:\n" + "\n".join(lines) +
            "\n\nMap: the network tree, with branches coloured by their BSP's stuck MW."
        ),
        "facts": [{"label": r.gsp, "value": r.stuck_mw, "unit": "MW stuck"} for r in top.itertuples()],
        "sources": [source("bsp_headroom_mw"), source("queue_mw"), source("grid_level_queue_mw")],
        "focus": {"view": "investor", "sort": "bsp", "network": True, "center": [first["lon"], first["lat"]], "zoom": 9.3},
    })

    # 3. Headroom that isn't really there --------------------------------------
    scorable = sites[sites["scorable"]]
    limited = scorable[scorable["limiting_level"] == "bsp"].copy()
    limited["gap"] = (limited["demand_headroom_mw"] - limited["queue_mw"]) - limited["effective_headroom_mw"]
    ex = limited.sort_values("gap", ascending=False).iloc[0]
    chapters.append({
        "id": "hidden",
        "title": "Headroom that isn't really there",
        "body": (
            f"Published headroom at a primary isn't the whole picture: the bulk supply point above it can be the real limit. "
            f"At **{_n(len(limited))}** of {_n(len(scorable))} primaries, the BSP leaves less room than the site's own figure. "
            f"Biggest gap: **{ex['name']}** shows {_mw(ex['demand_headroom_mw'] - ex['queue_mw'])} MW after its own queue, but "
            f"its BSP, {ex['bsp_name']}, leaves **{_mw(ex['effective_headroom_mw'])} MW** once everything queued under it is counted. "
            f"Map: the developer shortlist, counting BSP limits."
        ),
        "facts": [
            {"label": "Primaries limited by their BSP", "value": len(limited), "unit": "sites"},
            {"label": f"{ex['name']}: own figure", "value": ex["demand_headroom_mw"] - ex["queue_mw"], "unit": "MW"},
            {"label": f"{ex['name']}: counting its BSP", "value": ex["effective_headroom_mw"], "unit": "MW"},
        ],
        "sources": [source("demand_headroom_mw"), source("bsp_headroom_mw"), source("queue_mw")],
        "focus": {"view": "developer", "network": False, "select": ex["site_id"],
                  "center": [ex["lon"], ex["lat"]], "zoom": 11},
    })

    # 4. Running out ------------------------------------------------------------
    t = tl[tl["scenario"] == scenario].set_index("year")
    years = [y for y in (2026, 2030, 2035) if y in t.index]
    y0, y1 = years[0], years[1] if len(years) > 1 else years[0]
    neg_2030_ids = []
    hs = data.get("headroom_scenarios")
    if hs is not None:
        h = hs[(hs["scenario"] == scenario) & (hs["year"] == y1) & (hs["headroom_mw"] < 0)]
        neg_2030_ids = sorted(set(h["site_id"]) & set(scorable["site_id"]))
    chapters.append({
        "id": "runout",
        "title": "And it's running out",
        "body": (
            f"UKPN's own forecasts (DFES, {scenario} scenario) show published headroom shrinking year by year. "
            + " ".join(f"In {y}, **{_n(t.at[y, 'sites_negative'])}** primaries are forecast below zero." for y in years)
            + f" Total published headroom across these primaries falls from {_mw(t.at[y0, 'total_headroom_mw'])} MW in {y0} "
            f"to **{_mw(t.at[y1, 'total_headroom_mw'])} MW** in {y1}. "
            f"Map: the {_n(len(neg_2030_ids))} primaries forecast below zero in {y1} are ringed."
        ),
        "facts": [{"label": f"Primaries below zero, {y}", "value": int(t.at[y, "sites_negative"]), "unit": "sites"} for y in years],
        "sources": [source("headroom_2030_mw")],
        "focus": {"view": "investor", "sort": "score", "network": False, "highlight": neg_2030_ids, **UKPN_VIEW},
    })

    # 5. Big demand is already waiting -------------------------------------------
    ld = ldy[ldy["technology"] == "large_demand"]
    total_n, total_mva = ld["projects"].sum(), ld["import_capacity_mva"].sum()
    recent = ld[(ld["year"] >= 2021) & (ld["year"] <= 2024)]
    by_gsp = ld.groupby("gsp")[["projects", "import_capacity_mva"]].sum().sort_values("import_capacity_mva", ascending=False).head(3)
    gsp_xy = gm.set_index("gsp")[["lat", "lon"]]
    g0 = by_gsp.index[0]
    chapters.append({
        "id": "bigdemand",
        "title": "Big demand is already waiting",
        "body": (
            f"UKPN's large demand list counts **{_n(total_n)}** demand-only projects of 5 MVA and above that are committed "
            f"but not yet connected, **{_mw(total_mva)} MVA** in all — the data-centre-scale end of the queue. "
            f"{_n(recent['projects'].sum())} of them ({_mw(recent['import_capacity_mva'].sum())} MVA) applied between 2021 and 2024. "
            "Largest by grid supply point:\n"
            + "\n".join(f"- **{g}**: {_n(r.projects)} projects, {_mw(r.import_capacity_mva)} MVA" for g, r in by_gsp.iterrows())
            + "\n\nThis list only holds projects still waiting, so older ones drop out as they connect: it shows the "
            "backlog, not a growth rate."
        ),
        "facts": [
            {"label": "Large demand projects waiting", "value": int(total_n), "unit": "projects"},
            {"label": "Their import capacity", "value": total_mva, "unit": "MVA"},
        ],
        "sources": [source("large_demand")],
        "focus": {"view": "investor", "sort": "bsp", "network": True,
                  "center": [gsp_xy.at[g0, "lon"], gsp_xy.at[g0, "lat"]] if g0 in gsp_xy.index else UKPN_VIEW["center"],
                  "zoom": 9.3 if g0 in gsp_xy.index else UKPN_VIEW["zoom"]},
    })

    # 6. Where capacity would unlock the most ------------------------------------
    both = gm[(gm["stuck_mw"] > 0)].sort_values(["stuck_mw", "large_demand_mva"], ascending=False).head(5)
    chapters.append({
        "id": "where_to_act",
        "title": "Where new capacity would matter most",
        "body": (
            "Putting it together: the grid supply points where queued demand most exceeds published headroom, "
            "with the large demand waiting there.\n"
            + "\n".join(
                f"- **{r.gsp}**: {_mw(r.stuck_mw)} MW stuck, {_n(r.large_demand_count)} large demand projects "
                f"({_mw(r.large_demand_mva)} MVA), {_n(r.sites_limited_by_bsp)} primaries limited by their BSP"
                for r in both.itertuples())
            + "\n\nEach figure is published data; open any site on the map for its sources."
        ),
        "facts": [{"label": r.gsp, "value": r.stuck_mw, "unit": "MW stuck"} for r in both.itertuples()],
        "sources": [source("bsp_headroom_mw"), source("queue_mw"), source("large_demand")],
        "focus": {"view": "investor", "sort": "bsp", "network": True, **UKPN_VIEW},
    })

    # 7. What changes next ----------------------------------------------------------
    if len(snapshot_dates) >= 2 and len(ch):
        moved = ch[ch["level"] == "site"]["id"].nunique()
        body = (f"Between the {snapshot_dates[-2]} and {snapshot_dates[-1]} snapshots, figures moved at **{_n(moved)}** sites. "
                "Each refresh is kept, so movement in queues and headroom builds up over time.")
    else:
        body = (f"Every download is kept as a dated snapshot ({', '.join(snapshot_dates)} so far). "
                f"No UKPN dataset has been republished between them, so nothing has moved yet. UKPN publishes its Long Term "
                "Development Statement at the end of May and November; the next refresh after a publication will show how "
                "queues and headroom have shifted, site by site.")
    chapters.append({
        "id": "next",
        "title": "What changes next",
        "body": body,
        "facts": [{"label": "Snapshots kept", "value": len(snapshot_dates), "unit": "snapshots"}],
        "sources": [source("queue_mw")],
        "focus": {"view": "investor", "sort": "score", "network": False, **UKPN_VIEW},
    })

    for i, c in enumerate(chapters):
        c["number"] = i + 1
        seen, srcs = set(), []
        for src in c["sources"]:
            if src and src["dataset_id"] not in seen:
                seen.add(src["dataset_id"])
                srcs.append(src)
        c["sources"] = srcs
        for f in c["facts"]:
            f["value"] = _num(f["value"]) if isinstance(f["value"], float) else f["value"]
    return {"chapters": chapters, "snapshots": snapshot_dates, "scenario": scenario}
