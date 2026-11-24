"""The Fuse story: chapters built from the gold layer (Phase 10).

Every number in a chapter is computed here from gold / current tables at
request time; nothing is typed in by hand. Each chapter carries its sources
and a map focus the web app applies when the chapter opens.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from backend.assistant import _num



def _who(dnos: list[dict]) -> str:
    """'UK Power Networks', or 'UK Power Networks and SP Energy Networks'."""
    names = [d["name"] for d in dnos]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _whose(dnos: list[dict]) -> str:
    if len(dnos) > 1:
        return "The network operators'"
    name = dnos[0]["name"]
    return f"{name}'" if name.endswith("s") else f"{name}'s"


def _whole_view(dnos: list[dict]) -> dict:
    """Map view showing every network covered."""
    if len(dnos) == 1:
        return {"center": dnos[0]["map_center"], "zoom": dnos[0]["map_zoom"]}
    lons = [d["map_center"][0] for d in dnos]
    lats = [d["map_center"][1] for d in dnos]
    return {"center": [sum(lons) / len(lons), sum(lats) / len(lats)], "zoom": 5.6}


def _mw(v: float) -> str:
    """1 dp, rounded half-up like the map and the AI tools (−326.95 → −327.0)."""
    return f"{_num(v):,.1f}"


def _n(v: float) -> str:
    return f"{int(v):,}"


def build_story(data: dict[str, pd.DataFrame], source: callable, dnos: list[dict],
                snapshot_dates: list[str]) -> dict[str, Any]:
    """data: sites, bsps, gsps, site_scores, gold_gsp_mart, gold_headroom_timeline,
    gold_large_demand_by_year, gold_changes, large_demand. source(dno, field) -> source dict.
    dnos: the networks covered (backend.main._dnos); all wording about who publishes comes from it."""
    view = _whole_view(dnos)
    who = _who(dnos)

    def src(*fields: str) -> list[dict]:
        """Each field's source for every DNO covered, without repeats."""
        out = []
        for f in fields:
            for d in dnos:
                x = source(d["code"], f)
                if x and x not in out:
                    out.append(x)
        return out

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
            f"Across {who}, **{_mw(total_queue)} MW** of demand has been offered a connection and isn't "
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
        "sources": src("queue_mw", "demand_headroom_mw"),
        "focus": {"view": "investor", "sort": "stuck", "network": False, **view},
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
        "sources": src("bsp_headroom_mw", "queue_mw", "grid_level_queue_mw"),
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
        "sources": src("demand_headroom_mw", "bsp_headroom_mw", "queue_mw"),
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
            f"{_whose(dnos)} own forecasts (DFES, {scenario} scenario) show published headroom shrinking year by year. "
            + " ".join(f"In {y}, **{_n(t.at[y, 'sites_negative'])}** primaries are forecast below zero." for y in years)
            + f" Total published headroom across these primaries falls from {_mw(t.at[y0, 'total_headroom_mw'])} MW in {y0} "
            f"to **{_mw(t.at[y1, 'total_headroom_mw'])} MW** in {y1}. "
            f"Map: the {_n(len(neg_2030_ids))} primaries forecast below zero in {y1} are ringed."
        ),
        "facts": [{"label": f"Primaries below zero, {y}", "value": int(t.at[y, "sites_negative"]), "unit": "sites"} for y in years],
        "sources": src("headroom_2030_mw"),
        "focus": {"view": "investor", "sort": "score", "network": False, "highlight": neg_2030_ids, **view},
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
            f"The large demand list{'s' if len(dnos) > 1 else ''} published by {who} count{'' if len(dnos) > 1 else 's'} **{_n(total_n)}** demand-only projects of 5 MVA and above that are committed "
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
        "sources": src("large_demand"),
        "focus": {"view": "investor", "sort": "bsp", "network": True,
                  "center": [gsp_xy.at[g0, "lon"], gsp_xy.at[g0, "lat"]] if g0 in gsp_xy.index else view["center"],
                  "zoom": 9.3 if g0 in gsp_xy.index else view["zoom"]},
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
        "sources": src("bsp_headroom_mw", "queue_mw", "large_demand"),
        "focus": {"view": "investor", "sort": "bsp", "network": True, **view},
    })

    # 7. What changes next ----------------------------------------------------------
    if len(snapshot_dates) >= 2 and len(ch):
        moved = ch[ch["level"] == "site"]["id"].nunique()
        body = (f"Between the {snapshot_dates[-2]} and {snapshot_dates[-1]} snapshots, figures moved at **{_n(moved)}** sites. "
                "Each refresh is kept, so movement in queues and headroom builds up over time.")
    else:
        body = (f"Every download is kept as a dated snapshot ({', '.join(snapshot_dates)} so far). "
                "No dataset has been republished between them, so nothing has moved yet. Network operators publish their "
                "Long Term Development Statements at the end of May and November; the next refresh after a publication "
                "will show how queues and headroom have shifted, site by site.")
    chapters.append({
        "id": "next",
        "title": "What changes next",
        "body": body,
        "facts": [{"label": "Snapshots kept", "value": len(snapshot_dates), "unit": "snapshots"}],
        "sources": src("queue_mw"),
        "focus": {"view": "investor", "sort": "score", "network": False, **view},
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


# ------------------------------------------------------------------ Spain --

STORY_CONFIG = Path(__file__).resolve().parent.parent / "config" / "story.yaml"


def _km(lat0: float, lon0: float, lat: pd.Series, lon: pd.Series) -> pd.Series:
    """Great-circle distance in km."""
    p0, p = np.radians(lat0), np.radians(lat)
    a = np.sin((p - p0) / 2) ** 2 + np.cos(p0) * np.cos(p) * np.sin(np.radians(lon - lon0) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def _month(period: str | None) -> str | None:
    """'2026-10' -> 'October 2026'."""
    try:
        return pd.Timestamp(f"{period}-01").strftime("%B %Y")
    except (ValueError, TypeError):
        return None


def _pct(n: float, d: float) -> str:
    return f"{_num(100 * n / d):.1f}%" if d else "—"


def build_story_es(data: dict[str, pd.DataFrame], source: callable, dno: dict) -> dict[str, Any]:
    """Spain chapters, from the CNMC busbar data and the operator mart. Same shape as build_story."""
    sites, sc, ops = data["sites"], data["site_scores"], data["gold_operator_mart"]
    code = dno["code"]
    period = _month(dno.get("data_period")) or dno.get("snapshot_date")
    view = {"center": dno["map_center"], "zoom": dno["map_zoom"]}
    cfg = (yaml.safe_load(STORY_CONFIG.read_text()) or {}).get("ES", {}) if STORY_CONFIG.exists() else {}

    def src(*fields: str) -> list[dict]:
        out = []
        for f in fields:
            x = source(code, f)
            if x and x not in out:
                out.append(x)
        return out

    chapters: list[dict[str, Any]] = []
    n = len(sites)
    zero = int((sites["demand_headroom_mw"] <= 0).sum())
    flagged = int(sites["exclude_reason"].fillna("").str.contains("Nudo 0").sum())
    operators = sites["operator"].nunique()

    # 1. Full ------------------------------------------------------------------
    chapters.append({
        "id": "es_full",
        "title": "Spain's distribution grid is full",
        "body": (
            f"The CNMC's demand capacity map ({period}) covers **{_n(n)}** substation busbars above 1 kV from "
            f"**{_n(operators)}** distribution network operators. **{_n(zero)}** of them ({_pct(zero, n)}) show **zero** "
            f"firm demand capacity left: a new demand connection there can't be given firm access as published. "
            f"{_n(flagged)} busbars carry an operator flag (\"Nudo 0\") the data doesn't define and aren't scored. "
            "Map: busbars by stuck-demand score, ranked within Spain."
        ),
        "facts": [
            {"label": "Busbars published", "value": n, "unit": "busbars"},
            {"label": "With zero published headroom", "value": zero, "unit": "busbars"},
            {"label": "Distribution network operators", "value": operators, "unit": "operators"},
        ],
        "sources": src("demand_headroom_mw"),
        "focus": {"view": "investor", "sort": "score", "network": False, **view},
    })

    # 2. Waiting -------------------------------------------------------------
    stuck = sc[sc["site_id"].isin(sites["site_id"]) & (sc["stuck_mw"] > 0)]
    queue = sites["queue_mw"].sum()
    chapters.append({
        "id": "es_queue",
        "title": "Demand is waiting",
        "body": (
            f"Requests admitted but not yet evaluated add up to **{_mw(queue)} MW** across Spain's distribution busbars. "
            f"At **{_n(len(stuck))}** busbars the requests waiting are bigger than the published headroom: "
            f"**{_mw(stuck['stuck_mw'].sum())} MW** of demand the network can't take as published. "
            "The CNMC notes that capacities at neighbouring nodes affect each other, so totals are indicative. "
            "Map: busbars ranked by MW stuck."
        ),
        "facts": [
            {"label": "Requests waiting (admitted, not evaluated)", "value": queue, "unit": "MW"},
            {"label": "Busbars with stuck demand", "value": len(stuck), "unit": "busbars"},
            {"label": "Stuck at those busbars", "value": stuck["stuck_mw"].sum(), "unit": "MW"},
        ],
        "sources": src("queue_mw", "demand_headroom_mw"),
        "focus": {"view": "investor", "sort": "stuck", "network": False, **view},
    })

    # 3. Who runs them ---------------------------------------------------------
    top = ops[ops["stuck_rank"].notna()].sort_values("stuck_rank").head(5)
    chapters.append({
        "id": "es_operators",
        "title": "Which networks are stuck",
        "body": (
            "By distribution network operator, most stuck demand first:\n"
            + "\n".join(f"- **{r.operator_name}**: {_mw(r.stuck_mw)} MW stuck, {_pct(r.sites_zero_headroom, r.sites)} of its "
                        f"{_n(r.sites)} busbars at zero published headroom; most stuck: {r.top_site_name}"
                        for r in top.itertuples())
            + "\n\nOpen Distributors for every operator."
        ),
        "facts": [{"label": r.operator_name, "value": r.stuck_mw, "unit": "MW stuck"} for r in top.itertuples()],
        "sources": src("operator", "queue_mw", "demand_headroom_mw"),
        "focus": {"view": "investor", "sort": "stuck", "network": False, **view},
    })

    # 4. Small distributors ------------------------------------------------------
    big = set(dno["licence_areas"][:-1])  # every area but the last ("Small distributors")
    small = ops[~ops["licence_area"].isin(big)]
    small_sites = int(small["sites"].sum())
    small_zero = int(small["sites_zero_headroom"].sum())
    stuck_small = small[small["stuck_mw"] > 0].sort_values("stuck_mw", ascending=False)
    chapters.append({
        "id": "es_small",
        "title": "The small distributors",
        "body": (
            f"Besides the five large operators, **{_n(len(small))}** small distribution companies publish "
            f"{_n(small_sites)} busbars; {_n(small_zero)} of them ({_pct(small_zero, small_sites)}) show zero published "
            f"headroom. **{_n(len(stuck_small))}** have demand waiting beyond their published headroom"
            + (":\n" + "\n".join(f"- **{r.operator_name}** ({r.provinces}): {_mw(r.stuck_mw)} MW stuck across "
                                  f"{_n(r.sites)} busbar{'' if r.sites == 1 else 's'}" for r in stuck_small.head(5).itertuples()) if len(stuck_small) else ".")
        ),
        "facts": [
            {"label": "Small distributors", "value": len(small), "unit": "operators"},
            {"label": "Their busbars at zero headroom", "value": small_zero, "unit": "busbars"},
        ],
        "sources": src("operator", "demand_headroom_mw", "queue_mw"),
        "focus": {"view": "investor", "sort": "stuck", "network": False, "areas": [dno["licence_areas"][-1]], **view},
    })

    # 5. A worked example --------------------------------------------------------
    ex = cfg.get("example")
    here = sites[sites["site_id"].str.startswith(ex["site_prefix"])] if ex else sites.iloc[0:0]
    if len(here):
        lat0, lon0 = float(here["lat"].iloc[0]), float(here["lon"].iloc[0])
        near = sites.assign(km=_km(lat0, lon0, sites["lat"], sites["lon"]))
        near = near[near["km"] <= ex["radius_km"]]
        subs = near.assign(sub=near["name"].str.replace(r" [\d.]+ kV.*$", "", regex=True))
        by_sub = subs.groupby("sub").agg(km=("km", "min"), headroom=("demand_headroom_mw", "sum"),
                                         taken=("capacity_taken_mw", "sum"), queue=("queue_mw", "sum"))
        with_room = by_sub[by_sub["headroom"] > 0]
        own = here.sort_values(["voltage", "name"])
        sub_name = re.sub(r" [\d.]+ kV.*$", "", own["name"].iloc[0])

        def busbar(r) -> str:
            label = f"{r.voltage:g} kV" + (f" (busbar {m.group(1)})" if (m := re.search(r"busbar (\d+)", r.name)) else "")
            if isinstance(r.exclude_reason, str):
                return f"{label}: flagged by its operator, not scored"
            return f"{label}: {_mw(r.demand_headroom_mw)} MW published headroom, {_mw(r.capacity_taken_mw)} MW taken"

        chapters.append({
            "id": "es_example",
            "title": ex["title"],
            "body": (
                f"{ex['place']}: the local substation in the data is **{sub_name}**, run by {own['operator_name'].iloc[0]}.\n"
                + "\n".join(f"- {busbar(r)}" for r in own.itertuples())
                + f"\n\nWithin {ex['radius_km']} km there are **{_n(len(by_sub))}** substations; "
                f"**{_n(len(with_room))}** of them publish any firm demand capacity. "
                f"Requests waiting within that radius: {_mw(by_sub['queue'].sum())} MW."
            ),
            "facts": [
                {"label": f"Substations within {ex['radius_km']} km", "value": len(by_sub), "unit": "substations"},
                {"label": "With any published headroom", "value": len(with_room), "unit": "substations"},
            ],
            "sources": src("demand_headroom_mw", "capacity_taken_mw", "queue_mw"),
            "focus": {"view": "investor", "sort": "score", "network": False,
                      # open the busbar with the most capacity taken among those scored
                      "select": (own[own["exclude_reason"].isna()].sort_values("capacity_taken_mw").iloc[-1]
                                 if own["exclude_reason"].isna().any() else own.iloc[-1])["site_id"],
                      "highlight": near["site_id"].tolist(), "center": [lon0, lat0], "zoom": 9.6},
        })

    # 6. Next --------------------------------------------------------------------
    chapters.append({
        "id": "es_next",
        "title": "What changes next",
        "body": (
            "The CNMC updates its capacity maps every month, and every download is kept as a dated snapshot. "
            "Month by month, the map will show where capacity frees up, where requests pile up, and which operators "
            "are adding capacity."
        ),
        "facts": [{"label": "Data period", "value": period, "unit": ""}],
        "sources": src("demand_headroom_mw"),
        "focus": {"view": "investor", "sort": "score", "network": False, **view},
    })

    for i, c in enumerate(chapters):
        c["number"] = i + 1
        for f in c["facts"]:
            f["value"] = _num(f["value"]) if isinstance(f["value"], float) else f["value"]
    return {"chapters": chapters, "snapshots": [dno.get("snapshot_date")], "scenario": None}
