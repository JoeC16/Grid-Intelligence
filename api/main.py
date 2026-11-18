"""Grid Intelligence API. Reads data/grid.duckdb (built by `pipeline.run`).

Run:  uv run uvicorn api.main:app --reload

Endpoints
  GET /meta          filter options, scoring weights, data sources
  GET /sites         GeoJSON of substations, filterable
  GET /sites/{id}    every signal for one substation, each with its source
"""

from __future__ import annotations

import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

import duckdb
from dotenv import load_dotenv
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from pydantic import BaseModel, Field

from api import assistant
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
                                     connections_last_year, headroom_2030_mw)
            FROM sites t LEFT JOIN site_scores s USING (site_id)
            """
        ).df()
        return {
            "sites": sites,
            "gsps": con.execute("SELECT * FROM gsps").df(),
            "weights": con.execute("SELECT * FROM score_weights").df(),
            "sources": con.execute("SELECT * FROM field_sources").df(),
        }


PCT_COLS = [f"pct_{k}" for k in SIGNAL_DISPLAY]


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
        "sources": [{k: _clean(v) for k, v in r.items()} for r in data["sources"].to_dict("records")],
    }


@app.get("/sites")
def list_sites(
    licence_area: Annotated[list[str] | None, Query(description="e.g. LPN; repeat for several")] = None,
    voltage: Annotated[list[float] | None, Query(description="busbar kV, e.g. 11; repeat for several")] = None,
    min_score: Annotated[float | None, Query(ge=0, le=100)] = None,
    gsp: str | None = None,
    include_unscored: bool = True,
) -> dict:
    """Substations as a GeoJSON FeatureCollection (light properties for the map)."""
    df = _load()["sites"]
    if licence_area:
        df = df[df["licence_area"].isin([a.upper() for a in licence_area])]
    if voltage:
        df = df[df["voltage"].isin(voltage)]
    if gsp:
        df = df[df["gsp"].str.upper() == gsp.upper()]
    if min_score is not None:
        df = df[df["score"] >= min_score]
    elif not include_unscored:
        df = df[df["score"].notna()]

    props = ["site_id", "name", "licence_area", "voltage", "gsp", "score", "rank",
             "developer_rank", "stuck_rank", "queue_mw", "demand_headroom_mw", "headroom_after_queue_mw",
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
        elif key in ("stuck_mw", "oversubscription"):
            # derived from the demand queue and published headroom
            source, extra_sources = queue_source, [headroom_source]
        else:
            source = _source(dno, disp["field"])
        w = weights.get(key, {})
        if value is None:
            note = "Not published for this substation; scored on the other signals."
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
        "name": s["name"],
        "lat": s["lat"],
        "lon": s["lon"],
        "voltage": s["voltage"],
        "licence_area": s["licence_area"],
        "gsp": s["gsp"],
        "score": s["score"],
        "rank": s["rank"],
        "rank_of": int(sites["score"].notna().sum()),
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
            "source": _source(dno, "firm_capacity_mw"),
        },
        "headroom_2030": {"values": headroom_2030, "source": _source(dno, "headroom_2030_mw")},
        "location_source": _source(dno, "lat"),
        "gsp_context": gsp,
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


@app.post("/query")
def query(body: QueryIn) -> dict:
    """Answer a question with Claude, using search_sites / get_site / locate_place.

    Only numbers returned by those tools may appear in the answer; any that
    can't be matched to a tool result are listed in unverified_numbers.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503, detail="The AI ask box isn't configured: ANTHROPIC_API_KEY is not set.")
    import anthropic

    sites = _load()["sites"]
    try:
        result = assistant.ask(body.question, sites, _site_for_tool)
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="The AI service is busy. Try again in a minute.")
    except anthropic.APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"AI service error ({exc.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Couldn't reach the AI service.")

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
