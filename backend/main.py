"""Grid Intelligence API. Reads data/grid.duckdb (built by `pipeline.run`).

Run:  uv run uvicorn backend.main:app --reload

Endpoints
  GET /meta          filter options, scoring weights, data sources
  GET /sites         GeoJSON of substations, filterable
  GET /sites/{id}    every signal for one substation, each with its source
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import duckdb
from dotenv import load_dotenv
import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from pydantic import BaseModel, Field

from backend import assistant, guard
from backend.story import build_story, build_story_es
from pipeline.score import load_config

load_dotenv()  # local fallback only; in the cloud environment keys come from env vars

DB_PATH = Path(os.getenv("GRID_DB", Path(__file__).resolve().parent.parent / "data" / "grid.duckdb"))

DISCLAIMER = (
    "Published headroom is indicative firm capacity from the DNO's open data. "
    "It is not a guarantee of capacity available to connect."
)

# How each signal is shown. Keys match score_weights.key.
SIGNAL_DISPLAY = {
    "stuck_mw": {"field": "stuck_mw", "unit": "MW", "label": "Stuck demand (queue beyond headroom)"},
    "oversubscription": {"field": "oversubscription", "unit": "×", "label": "Oversubscription (queue / headroom)"},
    "headroom_tightness": {"field": "demand_headroom_mw", "unit": "MW", "label": "Published headroom"},
    "utilisation": {"field": "utilisation", "unit": "%", "label": "Utilisation (peak / firm)"},
    "recent_activity": {"field": "connections_last_year", "unit": "offers", "label": "Demand offers accepted, past year"},
    "future_squeeze": {"field": "headroom_2030_mw", "unit": "MW", "label": "Published headroom 2030"},
}

app = FastAPI(title="Grid Intelligence API", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ data --


@lru_cache(maxsize=1)
def _load() -> dict[str, pd.DataFrame]:
    """The DB is small (~1k sites), so load it once and serve from memory."""
    if not DB_PATH.exists():
        raise RuntimeError(f"{DB_PATH} not found. Run `uv run python -m pipeline.run` first.")
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        sites = con.execute(
            """
            SELECT t.*, s.* EXCLUDE (site_id, queue_mw, demand_headroom_mw,
                                     connections_last_year, headroom_2030_mw, effective_headroom_mw)
            FROM sites t LEFT JOIN site_scores s USING (site_id)
            """
        ).df()
        out = {
            "sites": sites,
            "gsps": con.execute("SELECT * FROM gsps").df(),
            "bsps": con.execute("SELECT * FROM bsps").df(),
            "edges": con.execute("SELECT * FROM edges").df(),
            "site_scores": con.execute("SELECT * FROM site_scores").df(),
            "headroom_scenarios": con.execute("SELECT * FROM headroom_scenarios").df(),
            "large_demand": con.execute("SELECT * FROM large_demand").df(),
            **{f"gold_{t}": con.execute(f"SELECT * FROM gold.{t}").df()
               for t in ("gsp_mart", "bsp_mart", "headroom_timeline", "large_demand_by_year", "changes",
                         "operator_mart")},
            "snapshots": sorted(con.execute("SELECT DISTINCT snapshot_date FROM silver.sites").df()["snapshot_date"]),
            "snapshots_by_dno": con.execute(
                "SELECT dno, list(DISTINCT snapshot_date ORDER BY snapshot_date) AS dates FROM silver.sites GROUP BY 1"
            ).df().set_index("dno")["dates"].map(list).to_dict(),
            "weights": con.execute("SELECT * FROM score_weights").df(),
            "sources": con.execute("SELECT * FROM field_sources").df(),
            "dnos": con.execute("SELECT * FROM dnos").df(),
        }
        # Tag upper-level nodes with their country (BSPs in GB, transmission nodes in Spain).
        out["bsps"] = out["bsps"].merge(
            out["dnos"][["code", "country"]].rename(columns={"code": "dno"}), on="dno", how="left")
        return out


PCT_COLS = [f"pct_{k}" for k in SIGNAL_DISPLAY]


def _country_data(data: dict, country: str) -> dict:
    """The same tables, limited to one country's sites, DNOs and marts."""
    dnos = set(data["dnos"].loc[data["dnos"]["country"] == country, "code"])
    ids = set(data["sites"].loc[data["sites"]["country"] == country, "site_id"])
    out = {}
    for k, v in data.items():
        if not isinstance(v, pd.DataFrame):
            out[k] = v
        elif "country" in v:
            out[k] = v[v["country"] == country]
        elif "dno" in v:
            out[k] = v[v["dno"].isin(dnos)]
        elif "code" in v and k == "dnos":
            out[k] = v[v["code"].isin(dnos)]
        elif "site_id" in v:
            out[k] = v[v["site_id"].isin(ids)]
        else:
            out[k] = v
    out["snapshots"] = sorted({d for code in dnos for d in data.get("snapshots_by_dno", {}).get(code, [])})
    return out


def _check_country(data: dict, country: str) -> str:
    country = country.upper()
    if country not in set(data["dnos"]["country"]):
        raise HTTPException(status_code=404, detail=f"No data for country {country!r}")
    return country


def _clean(v: Any, digits: int | None = 3) -> Any:
    """JSON-safe scalar: NaN/NA -> None, numpy -> python, floats rounded."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float):
        if math.isnan(v):
            return None
        return v if digits is None else round(v, digits)
    return v


def _row(df: pd.DataFrame) -> dict[str, Any]:
    return {k: _clean(v) for k, v in df.iloc[0].items()}


@lru_cache(maxsize=1)
def _sources() -> tuple[dict[str, dict], dict[str, dict]]:
    """field -> source, and dataset_id -> source, for one DNO-agnostic lookup."""
    src = _load()["sources"]
    by_field = {}
    by_dataset = {}
    for r in src.to_dict("records"):
        s = {"dataset_id": r["dataset_id"], "publish_date": r["publish_date"], "url": r["url"]}
        by_field[(r["dno"], r["field"])] = s
        by_dataset[r["dataset_id"]] = s
    return by_field, by_dataset


def _source(dno: str, field: str) -> dict | None:
    return _sources()[0].get((dno, field))


# ------------------------------------------------------------- endpoints --


def _view_meta(v, stored: pd.DataFrame) -> dict:
    base = {"key": v.key, "type": v.type, "label": v.label, "description": v.description}
    if v.type == "weighted":
        stored_w = {r["key"]: _clean(r["weight"]) for r in stored[stored["view"] == v.key].to_dict("records")}
        return {**base, "score_label": v.score_label, "weights": stored_w or v.weights}
    return {**base, "load_mw_default": v.load_mw_default, "filter_column": v.filter_column, "rank_by": v.rank_by}


def _dnos(data: dict) -> list[dict]:
    """The networks covered: names, areas, portal and licence for labels and attribution."""
    out = []
    for r in data["dnos"].to_dict("records"):
        out.append({
            "code": r["code"], "name": r["name"], "region": r["region"],
            "licence_areas": r["licence_areas"].split(","),
            "portal_name": r["portal_name"], "portal_url": r["portal_url"],
            "licence": r["licence"], "licence_url": r["licence_url"],
            "map_center": [r["map_lon"], r["map_lat"]], "map_zoom": r["map_zoom"],
            "site_count": int((data["sites"]["dno"] == r["code"]).sum()),
            "country": r.get("country", "GB"), "publisher": r.get("publisher") or r["name"],
            "has_topology": bool(r.get("has_topology", True)),
            "has_gsp": bool(r.get("has_gsp", True)), "upper_level": r.get("upper_level") or "BSP",
            "data_period": _clean(r.get("data_period")), "snapshot_date": _clean(r.get("snapshot_date")),
        })
    return out


COUNTRY_NAMES = {"GB": "Great Britain", "ES": "Spain"}


def _countries(data: dict) -> list[dict]:
    """Countries covered, each scored and ranked on its own (docs/SCORING.md)."""
    sites, dnos = data["sites"], _dnos(data)
    out = []
    for code in dict.fromkeys(d["country"] for d in dnos):  # keep pipeline order (GB first)
        mine = [d for d in dnos if d["country"] == code]
        s = sites[sites["country"] == code]
        lons = [d["map_center"][0] for d in mine]
        lats = [d["map_center"][1] for d in mine]
        out.append({
            "code": code, "name": COUNTRY_NAMES.get(code, code), "dnos": [d["code"] for d in mine],
            "licence_areas": [a for d in mine for a in d["licence_areas"] if a in set(s["licence_area"])],
            "voltages": sorted(float(v) for v in s["voltage"].dropna().unique()),
            "site_count": int(len(s)), "scored_count": int(s["score"].notna().sum()),
            "map_center": [sum(lons) / len(lons), sum(lats) / len(lats)],
            "map_zoom": min(d["map_zoom"] for d in mine) if len(mine) == 1 else min(d["map_zoom"] for d in mine) - 1,
            "has_topology": any(d["has_topology"] for d in mine),
            "has_gsp": any(d["has_gsp"] for d in mine),
            "upper_level": mine[0]["upper_level"],
            "data_period": next((d["data_period"] for d in mine if d["data_period"]), None),
        })
    return out


@app.get("/meta")
def meta() -> dict:
    data = _load()
    sites = data["sites"]
    signals, views = load_config()
    stored = data["weights"]  # weights the stored scores were computed with
    return {
        "disclaimer": DISCLAIMER,
        "licence_areas": sorted(sites["licence_area"].dropna().unique().tolist()),
        "voltages": sorted(float(v) for v in sites["voltage"].dropna().unique()),
        "site_count": int(len(sites)),
        "scored_count": int(sites["score"].notna().sum()),
        "signals": [
            {"key": sg.key, "label": sg.label, "description": sg.description, "direction": sg.direction}
            for sg in signals
        ],
        "views": [_view_meta(v, stored) for v in views],
        "headroom_2030_scenario": _clean(sites["headroom_2030_scenario"].iloc[0]),
        "dnos": _dnos(data),
        "countries": _countries(data),
        "sources": [{k: _clean(v) for k, v in r.items()} for r in data["sources"].to_dict("records")],
    }


@app.get("/sites")
def list_sites(
    licence_area: Annotated[list[str] | None, Query(description="e.g. LPN; repeat for several")] = None,
    voltage: Annotated[list[float] | None, Query(description="busbar kV, e.g. 11; repeat for several")] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    gsp: str | None = None,
    country: Annotated[str | None, Query(description="GB or ES; omit for every country")] = None,
    include_unscored: bool = True,
) -> dict:
    """Substations as a GeoJSON FeatureCollection (light properties for the map)."""
    df = _load()["sites"]
    if country:
        df = df[df["country"] == _check_country(_load(), country)]
    if licence_area:
        df = df[df["licence_area"].str.upper().isin([a.upper() for a in licence_area])]
    if voltage:
        df = df[df["voltage"].isin(voltage)]
    if gsp:
        df = df[df["gsp"].str.upper() == gsp.upper()]
    if min_score is not None:
        df = df[df["score"] >= min_score]
    elif not include_unscored:
        df = df[df["score"].notna()]

    props = ["site_id", "dno", "country", "operator", "name", "licence_area", "voltage", "gsp", "score", "rank",
             "developer_rank", "developer_rank_local", "stuck_rank", "queue_mw", "demand_headroom_mw",
             "headroom_after_queue_mw", "effective_headroom_mw", "limiting_level", "bsp_id",
             "stuck_mw", "oversubscription", *PCT_COLS]
    features = [
        {
            "type": "Feature",
            "id": i,
            "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
            # percentiles unrounded so the browser re-scores exactly like the pipeline
            "properties": {k: _clean(r[k], None if k in PCT_COLS else 3) for k in props},
        }
        for i, r in enumerate(df[props + ["lat", "lon"]].to_dict("records"))
    ]
    return {"type": "FeatureCollection", "count": len(features), "features": features}


@app.get("/sites/{site_id}")
def get_site(site_id: str) -> dict:
    data = _load()
    sites = data["sites"]
    match = sites[sites["site_id"] == site_id]
    if match.empty:
        raise HTTPException(status_code=404, detail=f"No site {site_id!r}")
    s = _row(match)
    dno = s["dno"]
    _, by_dataset = _sources()
    w_inv = data["weights"][data["weights"]["view"] == "investor"]
    weights = {w["key"]: w for w in w_inv.to_dict("records")}

    # queue figure may come from a fallback dataset for this site
    queue_source = by_dataset.get(s.get("queue_source")) or _source(dno, "queue_mw")
    queue_note = None
    if s.get("queue_source") == "none":
        queue_note = "No demand offers recorded for this substation."
    elif queue_source and queue_source != _source(dno, "queue_mw"):
        queue_note = "Not listed in the queue dataset; figure is demand offers from the past year."
    headroom_source = _source(dno, "demand_headroom_mw")

    signals = []
    for key, disp in SIGNAL_DISPLAY.items():
        value = s.get(disp["field"])
        note = None
        extra_sources: list[dict] = []
        if key == "utilisation":
            source = _source(dno, "observed_peak_mw")
            value = None if value is None else round(100 * value, 1)
            if source is None and s.get("capacity_taken_mw") is not None:
                # Spain: no peak demand published; share of firm access capacity already taken.
                source = _source(dno, "capacity_taken_mw")
                note = "Capacity already taken ÷ (taken + published headroom). The CNMC data has no peak demand."
        elif key in ("stuck_mw", "oversubscription"):
            # derived from the demand queue and published headroom
            source, extra_sources = queue_source, [headroom_source]
        else:
            source = _source(dno, disp["field"])
        w = weights.get(key, {})
        if value is None:
            note = ("Not scored (see above)." if not s.get("scorable")
                    else "Not published for this substation; scored on the other signals." if source
                    else "Not published by this network's data source; scored on the other signals.")
        signals.append({
            "key": key,
            "label": disp["label"],
            "value": value,
            "unit": disp["unit"],
            "percentile": s.get(f"pct_{key}"),
            "weight": _clean(w.get("weight")),
            "source": source,
            "extra_sources": [x for x in extra_sources if x],
            "note": note,
        })

    scenarios = sorted(k for k in s if k.startswith("headroom_2030_") and k not in
                       ("headroom_2030_mw", "headroom_2030_scenario"))
    headroom_2030 = [
        {"scenario": k.removeprefix("headroom_2030_").replace("_", " ").title(), "value": s[k],
         "default": k.removeprefix("headroom_2030_") == s["headroom_2030_scenario"].lower().replace(" ", "_")}
        for k in scenarios
    ]

    gsp = None
    if s.get("gsp"):
        g = data["gsps"][(data["gsps"]["gsp"] == s["gsp"]) & (data["gsps"]["dno"] == dno)]
        if not g.empty:
            row = _row(g)
            gsp = {
                "name": row["gsp"],
                "site_count": row["site_count"],
                "queue_mw": row["queue_mw"],
                "primary_queue_mw": row["primary_queue_mw"],
                "grid_level_queue_mw": row["grid_level_queue_mw"],
                "large_demand_count": row["large_demand_count"],
                "large_demand_mva": row["large_demand_mva"],
                "sources": {
                    "queue_mw": _source(dno, "grid_level_queue_mw"),
                    "large_demand": _source(dno, "large_demand"),
                },
            }

    return {
        "site_id": s["site_id"],
        "dno": dno,
        "country": s.get("country"),
        "operator": s.get("operator"),
        "operator_name": s.get("operator_name"),
        "province": s.get("province"),
        "municipality": s.get("municipality"),
        "reserved": bool(s.get("reserved")),
        "name": s["name"],
        "lat": s["lat"],
        "lon": s["lon"],
        "voltage": s["voltage"],
        "licence_area": s["licence_area"],
        "gsp": s["gsp"],
        "score": s["score"],
        "rank": s["rank"],
        "rank_of": int(sites.loc[sites["country"] == s.get("country"), "score"].notna().sum()),
        "queue": {"queue_mw": s.get("queue_mw"), "source": queue_source, "note": queue_note},
        "developer": {
            "headroom_after_queue_mw": s.get("headroom_after_queue_mw"),
            "rank_at_default_load": s.get("developer_rank"),
            "sources": [x for x in (headroom_source, queue_source) if x],
        },
        "scorable": s["scorable"],
        "exclude_reason": s["exclude_reason"],
        "score_missing": s["score_missing"],
        "signals": signals,
        "capacity": {
            "firm_capacity_mw": s["firm_capacity_mw"],
            "observed_peak_mw": s["observed_peak_mw"],
            "capacity_taken_mw": s.get("capacity_taken_mw"),
            "source": _source(dno, "firm_capacity_mw") or _source(dno, "capacity_taken_mw"),
        },
        "headroom_2030": {"values": headroom_2030, "source": _source(dno, "headroom_2030_mw")},
        "location_source": _source(dno, "lat"),
        "gsp_context": gsp,
        "upstream": _upstream(s, data, dno),
        "siblings": _siblings(s, sites),
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------- AI --


class QueryIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _site_for_tool(site_id: str) -> dict:
    try:
        return get_site(site_id)
    except HTTPException as exc:
        return {"error": exc.detail}


log = logging.getLogger("grid.ask")
logging.basicConfig(level=logging.INFO, format="%(message)s")


@app.post("/query")
def query(body: QueryIn, request: Request) -> dict:
    """Answer a question with Claude, using search_sites / get_site / locate_place.

    Only numbers returned by those tools may appear in the answer; any that
    can't be matched to a tool result are listed in unverified_numbers.
    """
    visitor = guard.check_access(request)  # off without ASK_ACCESS_CODE; code + rate limit
    if not assistant.anthropic_key():
        raise HTTPException(
            status_code=503,
            detail=f"The AI ask box isn't configured: set {' or '.join(assistant.KEY_ENV_VARS)}.",
        )
    import anthropic

    sites = _load()["sites"]
    started = time.monotonic()
    try:
        result = assistant.ask(body.question, sites, _site_for_tool, bsps=_load()["bsps"], gsps=_load()["gsps"],
                               dnos=_dnos(_load()))
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="The AI service is busy. Try again in a minute.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"AI service error ({exc.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Couldn't reach the AI service.")

    # One structured line per question (Vercel logs): no raw IPs, no question text.
    log.info(json.dumps({
        "event": "ask", "visitor": visitor, "question_chars": len(body.question),
        "tools": [c["name"] for c in result.tool_calls], "stop_reason": result.stop_reason,
        "unverified_numbers": len(result.unverified_numbers), "usage": result.usage,
        "seconds": round(time.monotonic() - started, 1), "model": result.model,
    }))
    by_id = sites.set_index("site_id")
    return {
        "answer": result.answer,
        "sites": [
            {"site_id": sid, "name": by_id.at[sid, "name"], "lat": _clean(by_id.at[sid, "lat"]), "lon": _clean(by_id.at[sid, "lon"])}
            for sid in result.site_ids
        ],
        "unverified_numbers": result.unverified_numbers,
        "tool_calls": result.tool_calls,
        "stop_reason": result.stop_reason,
        "model": result.model,
        "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------- topology --


def _upstream(s: dict, data: dict, dno: str) -> dict:
    """The path site → BSP → GSP with each level's figures and sources."""
    _, by_dataset = _sources()
    bsp = None
    if s.get("bsp_id"):
        b = data["bsps"][data["bsps"]["bsp_id"] == s["bsp_id"]]
        if not b.empty:
            r = _row(b)
            bsp = {
                "bsp_id": r["bsp_id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"], "site_id": r["site_id"],
                "matched": r["matched"], "note": r["note"], "site_count": r["site_count"],
                "headroom_mw": r["headroom_mw"], "queue_mw": r["queue_mw"],
                "headroom_after_queue_mw": r["headroom_after_queue_mw"], "stuck_mw": r["stuck_mw"],
                "is_this_site": r["site_id"] == s["site_id"],
                "level": "transmission" if str(r["bsp_id"]).startswith("TX") else "bsp",
                "cep_mw": r.get("cep_mw"), "free_bays": r.get("free_bays"),
                "admitted_mw": r.get("admitted_mw"), "occupied_mw": r.get("occupied_mw"),
                "sources": [x for x in (by_dataset.get(r["headroom_source"]), _source(dno, "queue_mw")) if x],
            }
    gsp = None
    if s.get("gsp"):
        g = data["gsps"][(data["gsps"]["gsp"] == s["gsp"]) & (data["gsps"]["dno"] == dno)]
        if not g.empty:
            r = _row(g)
            gsp = {
                "name": r["gsp"], "lat": r["lat"], "lon": r["lon"],
                "import_capacity_utilisation_pct": r.get("import_capacity_utilisation_pct"),
                "technical_limits_agreed": None if r.get("technical_limit_rag") is None else r["technical_limit_rag"] == "GREEN",
                "source": _source(dno, "gsp_utilisation"),
            }
    local = None if s.get("demand_headroom_mw") is None or s.get("queue_mw") is None else round(
        s["demand_headroom_mw"] - s["queue_mw"], 3)
    return {
        "headroom_after_queue_mw": local,
        "effective_headroom_mw": s.get("effective_headroom_mw"),
        "limiting_level": s.get("limiting_level"),
        "upstream_constrained": s.get("upstream_constrained"),
        "gsp_over_capacity": s.get("gsp_over_capacity"),
        "bsp": bsp,
        "gsp": gsp,
    }


def _siblings(s: dict, sites: pd.DataFrame) -> list[dict]:
    """Other sites on the same BSP, most effective headroom first."""
    if not s.get("bsp_id"):
        return []
    sib = sites[(sites["bsp_id"] == s["bsp_id"]) & (sites["site_id"] != s["site_id"])]
    sib = sib.sort_values("effective_headroom_mw", ascending=False, na_position="last")
    return [
        {"site_id": r["site_id"], "name": r["name"], "lat": _clean(r["lat"]), "lon": _clean(r["lon"]),
         "effective_headroom_mw": _clean(r["effective_headroom_mw"]), "queue_mw": _clean(r["queue_mw"])}
        for r in sib.to_dict("records")
    ]


@app.get("/bsps")
def list_bsps() -> dict:
    """Bulk supply points with rolled-up queue and stuck demand, and the sites under each."""
    data = _load()
    sites = data["sites"]
    children = sites.dropna(subset=["bsp_id"]).groupby("bsp_id")["site_id"].apply(list).to_dict()
    cols = ["bsp_id", "dno", "name", "licence_area", "lat", "lon", "site_id", "gsp", "matched", "note", "headroom_mw",
            "headroom_source", "site_count", "queue_mw", "headroom_after_queue_mw", "stuck_mw", "stuck_rank"]
    cols += [c for c in ("cep_mw", "free_bays") if c in data["bsps"]]
    rows = [{k: _clean(v) for k, v in r.items()} | {"site_ids": children.get(r["bsp_id"], [])}
            for r in data["bsps"][cols].to_dict("records")]
    sources = {d: _source(d, "bsp_headroom_mw") for d in data["dnos"]["code"]}
    return {"count": len(rows), "bsps": rows, "sources": sources}


# -------------------------------------------------------- story / network --


@app.get("/story")
def story(country: str = "GB") -> dict:
    """The Fuse story for one country: chapters built from the gold layer, each with sources and a map focus."""
    full = _load()
    country = _check_country(full, country)
    data = _country_data(full, country)
    dnos = [d for d in _dnos(full) if d["country"] == country]
    if any(d["has_gsp"] for d in dnos):  # GB-style tree with GSPs, DFES and large demand
        out = build_story(data, _source, dnos, data["snapshots"])
    else:
        out = build_story_es(data, _source, dnos[0])
    return _jsonable(out | {"country": country})


@app.get("/operators")
def list_operators(country: str = "ES") -> dict:
    """Distribution network operators in one country, most stuck demand first (gold.operator_mart)."""
    full = _load()
    country = _check_country(full, country)
    m = full["gold_operator_mart"]
    rows = [{k: _clean(v) for k, v in r.items()} for r in m[m["country"] == country].to_dict("records")]
    dnos = full["dnos"].loc[full["dnos"]["country"] == country, "code"]
    return {"country": country, "count": len(rows), "operators": rows,
            "sources": {d: _source(d, "operator") or _source(d, "demand_headroom_mw") for d in dnos},
            "note": "Sums over each operator's busbars are indicative: capacities at neighbouring nodes affect "
                    "each other, so they aren't strictly additive."}


@app.get("/gsps")
def list_gsps() -> dict:
    """GSP mart: the same core measures as sites and BSPs, rolled up to grid supply points."""
    rows = [{k: _clean(v) for k, v in r.items()} for r in _load()["gold_gsp_mart"].to_dict("records")]
    return {"count": len(rows), "gsps": rows}


@app.get("/network")
def network(country: str | None = None) -> dict:
    """The network tree as GeoJSON: edges (lines) and upper-level nodes (points).
    GB: GSP → BSP → primary. Spain: transmission node → busbar. country=None: both."""
    data = _load()
    if country:
        data = _country_data(data, _check_country(data, country))
    sites = data["sites"].set_index("site_id")
    bsps = data["bsps"].set_index("bsp_id")
    gsps = data["gold_gsp_mart"].dropna(subset=["lat", "lon"]).set_index("gsp")

    def xy(node_id: str):
        if node_id.startswith("GSP:"):
            g = node_id[4:]
            return [float(gsps.at[g, "lon"]), float(gsps.at[g, "lat"])] if g in gsps.index else None
        if node_id in bsps.index:  # BSP:… (GB) or TX:… (Spain's transmission nodes)
            if pd.notna(bsps.at[node_id, "lat"]):
                return [float(bsps.at[node_id, "lon"]), float(bsps.at[node_id, "lat"])]
            return None
        return [float(sites.at[node_id, "lon"]), float(sites.at[node_id, "lat"])] if node_id in sites.index else None

    features = []
    for e in data["edges"].itertuples():
        a, b = xy(e.child_id), xy(e.parent_id)
        if a and b and a != b:
            features.append({"type": "Feature", "properties": {"kind": f"edge_{e.kind}"},
                             "geometry": {"type": "LineString", "coordinates": [a, b]}})
    for bsp_id, r in bsps.iterrows():
        if pd.notna(r["lat"]):
            features.append({"type": "Feature", "properties": {
                "kind": "node_bsp", "id": bsp_id, "name": r["name"], "site_id": _clean(r["site_id"]),
                "stuck_mw": _clean(r["stuck_mw"]) or 0, "queue_mw": _clean(r["queue_mw"]),
                "headroom_mw": _clean(r["headroom_mw"]), "site_count": int(r["site_count"])},
                "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]}})
    for g, r in gsps.iterrows():
        features.append({"type": "Feature", "properties": {
            "kind": "node_gsp", "id": f"GSP:{g}", "name": g, "stuck_mw": _clean(r["stuck_mw"]) or 0,
            "queue_mw": _clean(r["queue_mw"]), "large_demand_mva": _clean(r["large_demand_mva"]),
            "bsp_count": int(r["bsp_count"]), "site_count": int(r["site_count"])},
            "geometry": {"type": "Point", "coordinates": [float(r["lon"]), float(r["lat"])]}})
    return {"type": "FeatureCollection", "features": features}


def _jsonable(v):
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return _clean(v)


@app.get("/health")
def health() -> dict:
    """For uptime monitors: is the data loaded, and how fresh is it. No secrets."""
    data = _load()
    snaps = data["snapshots"]
    return {
        "status": "ok",
        "latest_snapshot": snaps[-1] if snaps else None,
        "snapshots": len(snaps),
        "sites": int(len(data["sites"])),
        "scored": int(data["sites"]["score"].notna().sum()),
        "ask_enabled": bool(os.getenv("ASK_ACCESS_CODE")) and bool(assistant.anthropic_key()),
    }
