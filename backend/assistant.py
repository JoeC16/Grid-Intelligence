"""AI ask box: answers questions about the substations using Claude with tools.

Claude may only state numbers that its tools returned. That's enforced three
ways: the system prompt, tools that return every figure the answer could need
(distances included), and verify_numbers(), which checks each number in the
final answer against the tool results and reports any it can't find.

DNO-agnostic: it works on the normalised sites table.
"""

from __future__ import annotations

import json
import math
from decimal import ROUND_HALF_UP, Decimal
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2 as httpx
import pandas as pd

from pipeline.score import rank_desc

MODEL = "claude-opus-5-5"

# The Claude Code cloud environment doesn't pass ANTHROPIC_* variables through to
# sessions, so the key can also be supplied under this name.
KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "GRID_ANTHROPIC_API_KEY")


def anthropic_key() -> str | None:
    """The Claude API key from the first of KEY_ENV_VARS that is set."""
    return next((os.environ[v] for v in KEY_ENV_VARS if os.environ.get(v)), None)
MAX_ROUNDS = 8
PLACES_URL = "https://api.postcodes.io/places"
PLACES_SOURCE = "Ordnance Survey OS Open Names via postcodes.io (Open Government Licence v3.0)"

SYSTEM_PROMPT = """You answer questions about primary substations run by {coverage}, for grid investors and for developers looking to connect new demand such as data centres. The data covers demand only.

Use the tools to look things up. Every number in your answer must appear in a tool result: MW, distances, ranks, scores, counts and percentages. Don't estimate, round differently or do arithmetic of your own; if a figure you'd like isn't in a tool result, describe it in words or say the data doesn't include it.

Terms:
- Always say "published headroom", never "available capacity". Published headroom is indicative firm capacity from the network operator's open data, not a guarantee of capacity to connect.
- Queue = demand already offered a connection and not yet connected.
- Headroom after queue = published headroom minus the queue ahead.
- Stuck demand = queued demand beyond published headroom.
- Stuck-demand score = a 0-100 investor score (higher = more constrained).

The data has no connection dates or lead times. If asked how fast or soon something could connect, say that, and use headroom after queue (more is better) as the best available indicator.

The network is a tree: each primary substation hangs off a bulk supply point (BSP), which hangs off a grid supply point (GSP); some primaries are fed directly from the GSP. Effective headroom = the lower of a site's headroom after queue and its BSP's headroom after the queue of every site under it; it is what limits a new connection, and it is what the map's developer view ranks on. Use get_upstream to explain what limits a site, get_siblings for what shares its supply, and search_bsps for questions about BSPs. GSPs publish no MW headroom, only import utilisation (peak / capacity). For a BSP, put its own board's site_id (when it has one) in site_ids.

For any place name, call locate_place first, then search near the coordinates it returns. If the place is outside the area covered, say so and give the nearest sites the search returned.

Keep the answer short: a sentence or two, then the top few sites with their key figures. Put the site_ids you mention in site_ids, best first."""

ANSWER_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "Markdown answer for the user."},
            "site_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "site_ids mentioned in the answer, best first.",
            },
        },
        "required": ["answer", "site_ids"],
        "additionalProperties": False,
    },
}

_nullable = lambda t: {"anyOf": [t, {"type": "null"}]}  # noqa: E731

TOOLS = [
    {
        "name": "locate_place",
        "description": "Find the latitude and longitude of a UK place name (town, city, district). "
        "Returns up to 3 candidates, larger settlements first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Place name, e.g. 'Slough'."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_sites",
        "description": (
            "Search and rank primary substations across every network covered. Every filter is optional (null = no filter).\n"
            "rank_by:\n"
            "- 'score': investor stuck-demand score, highest first\n"
            "- 'stuck_mw': stuck demand in MW, largest first (sites with none are excluded)\n"
            "- 'effective_headroom': headroom left after the queue, counting the bulk supply point (BSP) above "
            "the site, highest first. This is the developer view on the map; combine with min_headroom_mw = the "
            "load size to keep only sites with enough published headroom\n"
            "- 'headroom_after_queue': the same but ignoring upstream (BSP) limits\n"
            "- 'distance': nearest first (needs near)\n"
            "Returns the total number of matches and the top results with their figures."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "rank_by": {"type": "string", "enum": ["score", "stuck_mw", "effective_headroom", "headroom_after_queue", "distance"]},
                "near": _nullable({
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number"},
                        "lon": {"type": "number"},
                        "radius_km": {"type": "number"},
                    },
                    "required": ["lat", "lon", "radius_km"],
                    "additionalProperties": False,
                }),
                "min_headroom_mw": _nullable({"type": "number"}),
                "licence_areas": _nullable({"type": "array", "items": {"type": "string", "enum": ["LPN", "SPN", "EPN"]}}),
                "voltages_kv": _nullable({"type": "array", "items": {"type": "number"}}),
                "gsp": _nullable({"type": "string"}),
                "min_score": _nullable({"type": "number"}),
                "name_contains": _nullable({"type": "string"}),
                "limit": _nullable({"type": "integer", "description": "Results to return, default 10, max 25."}),
            },
            "required": ["rank_by", "near", "min_headroom_mw", "licence_areas", "voltages_kv",
                         "gsp", "min_score", "name_contains", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_upstream",
        "description": "What limits a site upstream: the site's own headroom after queue, its bulk supply point (BSP: "
        "published headroom, queue under it, headroom left), its grid supply point (GSP: import utilisation), "
        "the effective headroom and which level limits it.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"site_id": {"type": "string"}},
            "required": ["site_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_siblings",
        "description": "The other sites fed from the same bulk supply point (BSP) as this site, most effective headroom first.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"site_id": {"type": "string"}},
            "required": ["site_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_bsps",
        "description": "Search and rank bulk supply points (BSPs). rank_by: 'stuck_mw' (queued demand under the BSP beyond "
        "its published headroom, largest first; BSPs with none are excluded), 'headroom_after_queue' (highest first) or "
        "'queue_mw' (largest first). Optional filters (null = none): near a point, licence areas. Returns the total "
        "number of matches and the top results.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "rank_by": {"type": "string", "enum": ["stuck_mw", "headroom_after_queue", "queue_mw"]},
                "near": _nullable({
                    "type": "object",
                    "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}, "radius_km": {"type": "number"}},
                    "required": ["lat", "lon", "radius_km"],
                    "additionalProperties": False,
                }),
                "licence_areas": _nullable({"type": "array", "items": {"type": "string", "enum": ["LPN", "SPN", "EPN"]}}),
                "limit": _nullable({"type": "integer", "description": "Results to return, default 10, max 25."}),
            },
            "required": ["rank_by", "near", "licence_areas", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_site",
        "description": "Everything about one substation: every signal with its source dataset and publish date, "
        "capacity, queue, 2030 published headroom for each DFES scenario, and its GSP (queue and large demand projects).",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"site_id": {"type": "string"}},
            "required": ["site_id"],
            "additionalProperties": False,
        },
    },
]


# ----------------------------------------------------------------- tools --


def haversine_km(lat1: float, lon1: float, lat2: pd.Series, lon2: pd.Series) -> pd.Series:
    r = 6371.0
    p1, p2 = math.radians(lat1), lat2.map(math.radians)
    dphi = p2 - p1
    dlmb = lon2.map(math.radians) - math.radians(lon1)
    a = (dphi / 2).map(math.sin) ** 2 + math.cos(p1) * p2.map(math.cos) * (dlmb / 2).map(math.sin) ** 2
    return 2 * r * a.map(lambda x: math.asin(math.sqrt(x)))


def _num(v: Any, digits: int = 1) -> float | None:
    """Round for the model; None for missing.

    Half-up on the shortest decimal form (422.15 -> 422.2), as the web app's
    number formatting does, so figures in answers match the map.
    """
    if v is None or pd.isna(v):
        return None
    q = Decimal(repr(float(v))).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return float(q)


def search_sites(sites: pd.DataFrame, args: dict) -> dict:
    """Filter + rank. Ranks are computed across all matching scorable sites (as the map does)."""
    df = sites[sites["score"].notna()].copy()  # scorable only
    if args.get("licence_areas"):
        df = df[df["licence_area"].isin(args["licence_areas"])]
    if args.get("voltages_kv"):
        df = df[df["voltage"].isin(args["voltages_kv"])]
    if args.get("gsp"):
        df = df[df["gsp"].fillna("").str.upper().str.contains(args["gsp"].upper(), regex=False)]
    if args.get("name_contains"):
        df = df[df["name"].str.lower().str.contains(args["name_contains"].lower(), regex=False)]
    if args.get("min_score") is not None:
        df = df[df["score"] >= args["min_score"]]
    if args.get("min_headroom_mw") is not None:
        df = df[df["demand_headroom_mw"] >= args["min_headroom_mw"]]
    near = args.get("near")
    if near:
        df["distance_km"] = haversine_km(near["lat"], near["lon"], df["lat"], df["lon"])
        df = df[df["distance_km"] <= near["radius_km"]]

    rank_by = args["rank_by"]
    if rank_by == "stuck_mw":
        df = df[df["stuck_mw"] > 0]
    if rank_by == "distance" and not near:
        return {"error": "rank_by 'distance' needs near."}
    sort_col = {"score": "score", "stuck_mw": "stuck_mw", "effective_headroom": "effective_headroom_mw",
                "headroom_after_queue": "headroom_after_queue_mw", "distance": "distance_km"}[rank_by]
    df["result_rank"] = rank_desc(-df[sort_col] if rank_by == "distance" else df[sort_col])
    df = df.sort_values(["result_rank", "site_id"])

    limit = max(1, min(int(args.get("limit") or 10), 25))
    rows = []
    for r in df.head(limit).to_dict("records"):
        row = {
            "result_rank": int(r["result_rank"]),
            "site_id": r["site_id"],
            "name": r["name"],
            "licence_area": r["licence_area"],
            "voltage_kv": _num(r["voltage"]),
            "gsp": r["gsp"],
            "published_headroom_mw": _num(r["demand_headroom_mw"]),
            "queue_mw": _num(r["queue_mw"]),
            "headroom_after_queue_mw": _num(r["headroom_after_queue_mw"]),
            "effective_headroom_mw": _num(r.get("effective_headroom_mw")),
            "limited_by": r.get("limiting_level"),
            "bsp": r.get("bsp_name"),
            "stuck_mw": _num(r["stuck_mw"]),
            "stuck_demand_score": _num(r["score"]),
            "score_rank_all": None if pd.isna(r["rank"]) else int(r["rank"]),
            "utilisation_pct": None if pd.isna(r["utilisation"]) else round(100 * r["utilisation"], 1),
            "published_headroom_2030_mw": _num(r["headroom_2030_mw"]),
        }
        if near:
            row["distance_km"] = round(float(r["distance_km"]), 1)
        rows.append(row)
    return {
        "total_matches": int(len(df)),
        "stuck_demand_score_scale": [0, 100],
        "results": rows,
        "note": "result_rank ranks the matches by rank_by; score_rank_all is the rank by stuck-demand score "
        "among all scored primaries in every network covered (one national ranking).",
    }


# ------------------------------------------------------- graph tools --


def _site_row(sites: pd.DataFrame, site_id: str) -> dict:
    match = sites[sites["site_id"] == site_id]
    if match.empty:
        raise KeyError(site_id)
    return match.iloc[0].to_dict()


def get_upstream(sites: pd.DataFrame, bsps: pd.DataFrame, gsps: pd.DataFrame, site_id: str) -> dict:
    s = _site_row(sites, site_id)
    local = None if pd.isna(s["demand_headroom_mw"]) or pd.isna(s["queue_mw"]) else s["demand_headroom_mw"] - s["queue_mw"]
    out: dict[str, Any] = {
        "site": {
            "site_id": site_id, "name": s["name"],
            "published_headroom_mw": _num(s["demand_headroom_mw"]), "queue_mw": _num(s["queue_mw"]),
            "headroom_after_queue_mw": _num(local),
        },
        "effective_headroom_mw": _num(s.get("effective_headroom_mw")),
        "limited_by": {"bsp": "its BSP", "primary": "the site itself"}.get(s.get("limiting_level"), s.get("limiting_level")),
    }
    bsp_id = s.get("bsp_id")
    if bsp_id is None or pd.isna(bsp_id):
        out["bsp"] = None
        out["fed_directly_from_gsp"] = True
    else:
        b = bsps[bsps["bsp_id"] == bsp_id].iloc[0].to_dict()
        out["bsp"] = {
            "bsp_id": bsp_id, "name": b["name"],
            "headroom_published": bool(b["matched"]) and not pd.isna(b["headroom_mw"]),
            "published_headroom_mw": _num(b["headroom_mw"]),
            "queue_under_it_mw": _num(b["queue_mw"]),
            "sites_under_it": int(b["site_count"]),
            "headroom_after_queue_mw": _num(b["headroom_after_queue_mw"]),
            "stuck_mw": _num(b["stuck_mw"]),
            "stuck_rank_among_bsps": None if pd.isna(b["stuck_rank"]) else int(b["stuck_rank"]),
            "this_site_is_its_own_board": b["site_id"] == site_id,
            "note": None if pd.isna(b["note"]) else b["note"],
        }
    g = gsps[gsps["gsp"] == s.get("gsp")] if len(gsps) else gsps
    if len(g):
        g0 = g.iloc[0]
        rag = g0.get("technical_limit_rag")
        out["gsp"] = {
            "name": g0["gsp"],
            "import_capacity_utilisation_pct": _num(g0.get("import_capacity_utilisation_pct")),
            "peak_at_or_above_capacity": bool(s.get("gsp_over_capacity")),
            "technical_limits_agreed_with_system_operator": None if pd.isna(rag) else rag == "GREEN",
            "note": "GSPs publish no MW headroom.",
        }
    else:
        out["gsp"] = None
    return out


def get_siblings(sites: pd.DataFrame, site_id: str) -> dict:
    s = _site_row(sites, site_id)
    bsp_id = s.get("bsp_id")
    if bsp_id is None or pd.isna(bsp_id):
        return {"site": s["name"], "bsp": None, "note": "Fed directly from its GSP: no BSP, so no siblings.", "siblings": []}
    sib = sites[(sites["bsp_id"] == bsp_id) & (sites["site_id"] != site_id)]
    sib = sib.sort_values("effective_headroom_mw", ascending=False, na_position="last")
    return {
        "site": s["name"],
        "bsp": s.get("bsp_name"),
        "sibling_count": int(len(sib)),
        "siblings": [
            {"site_id": r["site_id"], "name": r["name"],
             "published_headroom_mw": _num(r["demand_headroom_mw"]), "queue_mw": _num(r["queue_mw"]),
             "effective_headroom_mw": _num(r["effective_headroom_mw"]),
             "limited_by": {"bsp": "its BSP", "primary": "the site itself"}.get(r["limiting_level"], r["limiting_level"])}
            for r in sib.to_dict("records")
        ],
    }


def search_bsps(bsps: pd.DataFrame, args: dict) -> dict:
    df = bsps.copy()
    if args.get("licence_areas"):
        df = df[df["licence_area"].isin(args["licence_areas"])]
    near = args.get("near")
    if near:
        df = df.dropna(subset=["lat", "lon"])
        df["distance_km"] = haversine_km(near["lat"], near["lon"], df["lat"], df["lon"])
        df = df[df["distance_km"] <= near["radius_km"]]
    rank_by = args["rank_by"]
    col = {"stuck_mw": "stuck_mw", "headroom_after_queue": "headroom_after_queue_mw", "queue_mw": "queue_mw"}[rank_by]
    df = df.dropna(subset=[col])
    if rank_by == "stuck_mw":
        df = df[df["stuck_mw"] > 0]
    df["result_rank"] = rank_desc(df[col])
    df = df.sort_values(["result_rank", "bsp_id"])
    limit = max(1, min(int(args.get("limit") or 10), 25))
    rows = []
    for r in df.head(limit).to_dict("records"):
        row = {
            "result_rank": int(r["result_rank"]), "bsp_id": r["bsp_id"], "name": r["name"],
            "licence_area": r["licence_area"], "gsp": r["gsp"],
            "own_board_site_id": None if pd.isna(r["site_id"]) else r["site_id"],
            "sites_under_it": int(r["site_count"]),
            "published_headroom_mw": _num(r["headroom_mw"]), "queue_under_it_mw": _num(r["queue_mw"]),
            "headroom_after_queue_mw": _num(r["headroom_after_queue_mw"]), "stuck_mw": _num(r["stuck_mw"]),
            "stuck_rank_among_bsps": None if pd.isna(r["stuck_rank"]) else int(r["stuck_rank"]),
        }
        if near:
            row["distance_km"] = round(float(r["distance_km"]), 1)
        rows.append(row)
    return {"total_matches": int(len(df)), "results": rows}


def locate_place(name: str, fetch: Callable[[str, dict], dict] | None = None) -> dict:
    """Geocode a UK place name with OS Open Names (postcodes.io). Larger settlements first."""
    order = {"City": 0, "Town": 1, "Suburban Area": 2, "Other Settlement": 3, "Village": 4, "Hamlet": 5}
    fetch = fetch or _http_get_json
    try:
        data = fetch(PLACES_URL, {"q": name, "limit": 20})
    except Exception as exc:  # noqa: BLE001 - surface any lookup failure to the model
        return {"error": f"Place lookup failed: {type(exc).__name__}"}
    results = data.get("result") or []
    results = [r for r in results if r.get("country") == "England"] or results
    results.sort(key=lambda r: (order.get(r.get("local_type"), 9), r.get("name_1", "") != name.title()))
    out = [
        {
            "name": r.get("name_1"),
            "type": r.get("local_type"),
            "area": r.get("district_borough") or r.get("county_unitary"),
            "region": r.get("region"),
            "lat": round(r["latitude"], 4),
            "lon": round(r["longitude"], 4),
        }
        for r in results[:3]
    ]
    if not out:
        return {"error": f"No UK place called {name!r} found."}
    return {"candidates": out, "source": PLACES_SOURCE}


def _http_get_json(url: str, params: dict) -> dict:
    # Generic client name only: no user or project details go to the service.
    r = httpx.get(url, params=params, timeout=10.0, headers={"User-Agent": "grid-intelligence-demo"})
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------- number check --

_NUM = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")
# A whole year used as a label ("headroom in 2030") isn't a data claim, unless a unit follows.
_YEAR_AS_LABEL = re.compile(r"(?<![\w.])(199\d|20\d\d|2100)(?!\d)(?!\.\d)(?!,\d{3})(?!\s*(?:MW|MVA|kV|km|%|×|x\b))")


def _numbers(text: str) -> list[str]:
    return [m.group(0).replace(",", "") for m in _NUM.finditer(text)]


def verify_numbers(answer: str, tool_outputs: list[str], question: str) -> list[str]:
    """Numbers in the answer that appear neither in a tool result nor in the question.

    A number matches a tool value if it equals the value rounded to the same
    number of decimal places (so "132.6" matches 132.6 and "133" matches 132.6
    rounded to 0 dp). Signs are ignored ("−3.1 MW" vs "3.1 MW below"). Whole
    years 1990-2100 used as labels are skipped, unless a unit follows them.
    """
    answer = _YEAR_AS_LABEL.sub(" ", answer)
    known: set[float] = set()
    for out in tool_outputs:
        known.update(abs(float(n)) for n in _numbers(out))
    asked = {abs(float(n)) for n in _numbers(question)}
    unverified = []
    for raw in _numbers(answer):
        v = abs(float(raw))
        dp = len(raw.split(".")[1]) if "." in raw else 0
        if v in asked or any(round(k, dp) == v for k in known):
            continue
        unverified.append(raw)
    return unverified


# ------------------------------------------------------------------ loop --


@dataclass
class Answer:
    answer: str
    site_ids: list[str]
    unverified_numbers: list[str]
    tool_calls: list[dict] = field(default_factory=list)
    stop_reason: str | None = None
    model: str | None = None
    usage: dict = field(default_factory=dict)  # tokens summed over the tool loop


def _coverage(dnos: list[dict]) -> str:
    """'UK Power Networks (UKPN) in London, ... (licence areas LPN, SPN, EPN)' for each network."""
    return "; and ".join(
        f"{d['name']} ({d['code']}) in {d['region']} (licence areas {', '.join(d['licence_areas'])})" for d in dnos)


def system_prompt(dnos: list[dict]) -> str:
    return SYSTEM_PROMPT.replace("{coverage}", _coverage(dnos))


def tools_for(areas: list[str]) -> list[dict]:
    """TOOLS with the licence_areas enums set to the areas in the data."""
    tools = json.loads(json.dumps(TOOLS))
    for t in tools:
        la = t["input_schema"]["properties"].get("licence_areas")
        if la:
            la["anyOf"][0]["items"]["enum"] = sorted(areas)
    return tools


def _dnos_from_sites(sites: pd.DataFrame) -> list[dict]:
    """Fallback coverage when the caller passes no DNO descriptions (tests, scripts)."""
    out = []
    for code, g in sites.groupby("dno") if "dno" in sites else [("DNO", sites)]:
        out.append({"code": code, "name": code, "region": "Great Britain",
                    "licence_areas": sorted(g["licence_area"].dropna().unique())})
    return out


def ask(question: str, sites: pd.DataFrame, get_site: Callable[[str], dict], client: Any = None,
        bsps: pd.DataFrame | None = None, gsps: pd.DataFrame | None = None,
        dnos: list[dict] | None = None) -> Answer:
    """Run the tool loop for one question. bsps/gsps feed the graph tools; dnos (backend.main._dnos)
    names the networks covered in the system prompt."""
    dnos = dnos or _dnos_from_sites(sites)
    system = system_prompt(dnos)
    tools = tools_for([a for d in dnos for a in d["licence_areas"]])
    bsps = bsps if bsps is not None else pd.DataFrame()
    gsps = gsps if gsps is not None else pd.DataFrame()
    import anthropic

    if client is None:
        key = anthropic_key()
        if not key:
            raise RuntimeError(f"No Claude API key: set {' or '.join(KEY_ENV_VARS)}")
        client = anthropic.Anthropic(api_key=key)

    messages: list[dict] = [{"role": "user", "content": question}]
    tool_outputs: list[str] = []
    calls: list[dict] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "requests": 0}

    for _ in range(MAX_ROUNDS):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={"effort": "medium", "format": ANSWER_FORMAT},
            cache_control={"type": "ephemeral"},
            # On a policy decline, re-run on a fallback model inside the same call.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        u = getattr(response, "usage", None)
        usage["requests"] += 1
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            usage[k] += int(getattr(u, k, 0) or 0) if u is not None else 0
        if response.stop_reason == "refusal":
            return Answer("I can't help with that question.", [], [], calls, "refusal", response.model)
        if response.stop_reason != "tool_use":
            break
        # Append the assistant turn unchanged (thinking blocks included), then all results in one message.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            out = run_tool(block.name, block.input, sites, get_site, bsps, gsps)
            text = json.dumps(out, default=str)
            tool_outputs.append(text)
            calls.append({"name": block.name, "input": block.input})
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": text,
                            "is_error": "error" in out})
        messages.append({"role": "user", "content": results})
    else:
        return Answer("Sorry, that took too many lookups. Try a narrower question.", [], [], calls,
                      "max_rounds", response.model)

    if response.stop_reason == "max_tokens":
        return Answer("Sorry, the answer was cut off. Try a narrower question.", [], [], calls,
                      "max_tokens", response.model)
    text = next((b.text for b in response.content if b.type == "text"), "")
    data = json.loads(text)
    known_ids = set(sites["site_id"])
    site_ids = [s for s in data.get("site_ids", []) if s in known_ids]
    return Answer(
        answer=data["answer"],
        site_ids=site_ids,
        unverified_numbers=verify_numbers(data["answer"], tool_outputs, question),
        tool_calls=calls,
        stop_reason=response.stop_reason,
        model=response.model,
        usage=usage,
    )


def site_for_model(site: dict) -> dict:
    """get_site output with percentiles on the 0-100 scale people quote (99.8, not 0.998)."""
    if "signals" not in site:
        return site
    signals = [
        {**s, "percentile": None if s.get("percentile") is None else round(100 * s["percentile"], 1)}
        for s in site["signals"]
    ]
    return {**site, "signals": signals, "stuck_demand_score_scale": [0, 100],
            "percentile_note": "percentile is 0-100 among all primaries covered; 100 = most stuck on that signal."}


def run_tool(name: str, args: dict, sites: pd.DataFrame, get_site: Callable[[str], dict],
             bsps: pd.DataFrame | None = None, gsps: pd.DataFrame | None = None) -> dict:
    bsps = bsps if bsps is not None else pd.DataFrame()
    gsps = gsps if gsps is not None else pd.DataFrame()
    try:
        if name == "search_sites":
            return search_sites(sites, args)
        if name == "get_upstream":
            return get_upstream(sites, bsps, gsps, args["site_id"])
        if name == "get_siblings":
            return get_siblings(sites, args["site_id"])
        if name == "search_bsps":
            return search_bsps(bsps, args)
        if name == "get_site":
            return site_for_model(get_site(args["site_id"]))
        if name == "locate_place":
            return locate_place(args["name"])
        return {"error": f"Unknown tool {name}"}
    except KeyError as exc:
        return {"error": f"Not found: {exc}"}
    except Exception as exc:  # noqa: BLE001 - report tool failures to the model, don't crash the request
        return {"error": f"{name} failed: {type(exc).__name__}: {exc}"}
