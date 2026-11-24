"""AI ask box: tools, number verification and the tool loop. No real model calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import assistant
from backend.main import DB_PATH, _load, _site_for_tool, app

needs_db = pytest.mark.skipif(not Path(DB_PATH).exists(), reason="run pipeline.run first")


# ------------------------------------------------------------ verify_numbers


def test_numbers_from_tools_pass():
    tools = [json.dumps({"published_headroom_mw": 137.0, "queue_mw": 4.4, "headroom_after_queue_mw": 132.6,
                         "distance_km": 18.3, "result_rank": 1})]
    answer = "Osborn St B has 137.0 MW published headroom, 4.4 MW queued, 132.6 MW left, 18.3 km away (rank 1)."
    assert assistant.verify_numbers(answer, tools, "q") == []


def test_rounded_to_fewer_decimals_passes():
    assert assistant.verify_numbers("about 133 MW left", [json.dumps({"x": 132.6})], "q") == []


def test_invented_number_flagged():
    assert assistant.verify_numbers("roughly 45 MW spare", [json.dumps({"x": 132.6})], "q") == ["45"]


def test_numbers_from_question_allowed():
    assert assistant.verify_numbers("for a 50 MW load within 30 km", [], "50 MW within 30 km of Slough?") == []


def test_year_labels_skipped_but_year_valued_mw_checked():
    tools = [json.dumps({"published_headroom_2030_mw": -2.3})]
    assert assistant.verify_numbers("Published headroom in 2030 is -2.3 MW.", tools, "q") == []
    assert assistant.verify_numbers("By 2030, 2030 MW is queued.", tools, "q") == ["2030"]
    assert assistant.verify_numbers("Over 2030-2035 things tighten.", tools, "q") == []


def test_score_scale_is_tool_data():
    out = assistant.search_sites(pd.DataFrame(columns=_EMPTY_COLS).astype({"score": float}), _args(rank_by="score"))
    assert assistant.verify_numbers("a score (0–100) of 98.0", [json.dumps(out), json.dumps({"s": 98.0})], "q") == []


def test_negative_and_thousands():
    tools = [json.dumps({"x": -3.1, "y": 1234.5})]
    assert assistant.verify_numbers("−3.1 MW and 1,234.5 MW", tools, "q") == []


# --------------------------------------------------------------- percentiles


def test_site_for_model_scales_percentiles():
    site = {"site_id": "X", "signals": [{"key": "stuck_mw", "percentile": 0.998}, {"key": "u", "percentile": None}]}
    out = assistant.site_for_model(site)
    assert [s["percentile"] for s in out["signals"]] == [99.8, None]
    assert site["signals"][0]["percentile"] == 0.998  # the API's own copy is untouched
    assert assistant.verify_numbers("99.8th percentile", [json.dumps(out)], "q") == []
    assert assistant.site_for_model({"error": "no site"}) == {"error": "no site"}


_EMPTY_COLS = ["site_id", "name", "licence_area", "voltage", "gsp", "score", "rank", "lat", "lon",
               "demand_headroom_mw", "queue_mw", "headroom_after_queue_mw", "stuck_mw",
               "utilisation", "headroom_2030_mw"]


# -------------------------------------------------------------- locate_place


def test_locate_place_prefers_towns_in_england():
    fake = {"result": [
        {"name_1": "Slough", "local_type": "Hamlet", "country": "Wales", "county_unitary": "Monmouthshire",
         "region": "Wales", "latitude": 51.71, "longitude": -2.85},
        {"name_1": "Slough", "local_type": "Town", "country": "England", "district_borough": None,
         "county_unitary": "Slough", "region": "South East", "latitude": 51.5095, "longitude": -0.5954},
        {"name_1": "Slough Green", "local_type": "Village", "country": "England", "county_unitary": "West Sussex",
         "region": "South East", "latitude": 51.0, "longitude": -0.2},
    ]}
    out = assistant.locate_place("Slough", fetch=lambda url, params: fake)
    assert out["candidates"][0] == {"name": "Slough", "type": "Town", "area": "Slough",
                                    "region": "South East", "lat": 51.5095, "lon": -0.5954}
    assert all(c["region"] != "Wales" for c in out["candidates"])


def test_locate_place_errors_are_reported():
    def boom(url, params):
        raise TimeoutError
    assert "error" in assistant.locate_place("X", fetch=boom)
    assert "error" in assistant.locate_place("Nowhere", fetch=lambda u, p: {"result": []})


# -------------------------------------------------------------- search_sites


def _args(**kw):
    base = {k: None for k in ["near", "min_headroom_mw", "licence_areas", "operator_contains", "voltages_kv", "gsp",
                              "min_score", "name_contains", "limit"]}
    return {**base, "country": "GB", **kw}


@needs_db
def test_search_by_score_matches_map_ranking():
    out = assistant.search_sites(_load()["sites"], _args(rank_by="score", limit=3))
    first = out["results"][0]
    assert first["name"] == "Bow 11kV" and first["result_rank"] == 1 and first["score_rank_in_country"] == 1
    assert out["total_matches"] == 959


@needs_db
def test_search_developer_matches_pipeline():
    sites = _load()["sites"]
    pairs = [("effective_headroom", "developer_rank"), ("headroom_after_queue", "developer_rank_local")]
    for country in ("GB", "ES"):
        mine = sites[sites["country"] == country]
        for rank_by, col in pairs:
            out = assistant.search_sites(sites, _args(rank_by=rank_by, min_headroom_mw=50, limit=25, country=country))
            assert out["total_matches"] == int(mine[col].notna().sum())
            for r in out["results"]:
                assert r["result_rank"] == sites.loc[sites.site_id == r["site_id"], col].iloc[0], (rank_by, r)


@needs_db
def test_search_stuck_matches_pipeline():
    out = assistant.search_sites(_load()["sites"], _args(rank_by="stuck_mw", limit=3))
    assert [r["name"] for r in out["results"]] == ["Northfleet East 33kV", "Rye House 33kV", "Stowmarket Grid 33kV"]
    assert out["total_matches"] == 124


@needs_db
def test_search_near_point_filters_and_reports_distance():
    out = assistant.search_sites(_load()["sites"], _args(rank_by="distance", near={"lat": 51.5095, "lon": -0.5954, "radius_km": 30}))
    assert out["total_matches"] > 0
    dists = [r["distance_km"] for r in out["results"]]
    assert dists == sorted(dists) and max(dists) <= 30


@needs_db
def test_distance_without_near_is_an_error():
    assert "error" in assistant.search_sites(_load()["sites"], _args(rank_by="distance"))


@needs_db
def test_get_site_tool_unknown_id():
    assert "error" in _site_for_tool("NOPE")


# ------------------------------------------------------------------ the loop


class FakeClient:
    """Scripted stand-in for anthropic.Anthropic: plays back canned responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _tool_use(name, inp, id_="t1"):
    return SimpleNamespace(type="tool_use", name=name, input=inp, id=id_)


def _text(obj):
    return SimpleNamespace(type="text", text=json.dumps(obj))


@needs_db
def test_loop_runs_tools_then_returns_structured_answer():
    sites = _load()["sites"]
    client = FakeClient([
        SimpleNamespace(stop_reason="tool_use", model=assistant.MODEL,
                        content=[_tool_use("search_sites", _args(rank_by="stuck_mw", limit=1))]),
        SimpleNamespace(stop_reason="end_turn", model=assistant.MODEL, content=[_text({
            "answer": "Northfleet East 33kV has the most stuck demand: 303.8 MW (and 999 MW invented).",
            "site_ids": ["SPN-S000000009937", "NOT-A-SITE"]})]),
    ])
    out = assistant.ask("Where is the most demand stuck?", sites, _site_for_tool, client=client)
    assert out.tool_calls == [{"name": "search_sites", "input": _args(rank_by="stuck_mw", limit=1)}]
    assert out.site_ids == ["SPN-S000000009937"]  # unknown ids dropped
    assert out.unverified_numbers == ["999"]  # 33 (name) and 303.8 come from the tool result
    # second request carries the tool result back, after the assistant turn
    second = client.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and second[2]["content"][0]["type"] == "tool_result"
    # request shape: fallbacks on, structured answer, no forced tool choice
    assert client.calls[0]["fallbacks"] == "default"
    assert client.calls[0]["output_config"]["format"]["type"] == "json_schema"
    assert "tool_choice" not in client.calls[0]


@needs_db
def test_loop_handles_refusal():
    client = FakeClient([SimpleNamespace(stop_reason="refusal", model=assistant.MODEL, content=[])])
    out = assistant.ask("q", _load()["sites"], _site_for_tool, client=client)
    assert out.stop_reason == "refusal" and out.site_ids == []


def test_key_from_either_variable(monkeypatch):
    for v in assistant.KEY_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    assert assistant.anthropic_key() is None
    monkeypatch.setenv("GRID_ANTHROPIC_API_KEY", "grid-key")
    assert assistant.anthropic_key() == "grid-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "main-key")
    assert assistant.anthropic_key() == "main-key"  # the standard name wins


def test_query_without_key_is_503(monkeypatch):
    for v in assistant.KEY_ENV_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("ASK_ACCESS_CODE", "letmein")
    r = TestClient(app).post("/query", json={"question": "Where is demand stuck?"}, headers={"X-Access-Code": "letmein"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


# ------------------------------------------------------------ protection


def test_ask_is_off_without_an_access_code(monkeypatch):
    monkeypatch.delenv("ASK_ACCESS_CODE", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "would-be-billable")
    r = TestClient(app).post("/query", json={"question": "Where is demand stuck?"})
    assert r.status_code == 503 and "isn't enabled" in r.json()["detail"]


def test_ask_rejects_a_wrong_code(monkeypatch):
    monkeypatch.setenv("ASK_ACCESS_CODE", "letmein")
    r = TestClient(app).post("/query", json={"question": "Where is demand stuck?"}, headers={"X-Access-Code": "nope"})
    assert r.status_code == 401


def test_ask_rate_limit(monkeypatch):
    from backend import guard
    guard._hits.clear()
    monkeypatch.setenv("ASK_ACCESS_CODE", "letmein")
    monkeypatch.setenv("ASK_RATE_PER_HOUR", "2")
    for v in assistant.KEY_ENV_VARS:  # stop before any model call
        monkeypatch.delenv(v, raising=False)
    c = TestClient(app)
    codes = [c.post("/query", json={"question": "Where is demand stuck?"}, headers={"X-Access-Code": "letmein"}).status_code
             for _ in range(3)]
    assert codes == [503, 503, 429]  # 503 = past the guard, then no key; third is over the limit
    guard._hits.clear()


# ------------------------------------------------------------ graph tools


def _site_id(name):
    s = _load()["sites"]
    return s.loc[s["name"] == name, "site_id"].iloc[0]


@needs_db
def test_get_upstream_matches_map_panel():
    from backend.main import get_site
    d = _load()
    sid = _site_id("Kingston Grid 33kV")
    out = assistant.get_upstream(d["sites"], d["bsps"], d["gsps"], sid)
    panel = get_site(sid)["upstream"]  # what the side panel shows
    assert out["effective_headroom_mw"] == assistant._num(panel["effective_headroom_mw"]) == 110.3
    assert out["limited_by"] == "its BSP"
    assert out["bsp"]["name"] == panel["bsp"]["name"] and out["bsp"]["this_site_is_its_own_board"]
    assert out["gsp"]["name"] == panel["gsp"]["name"]


@needs_db
def test_get_upstream_direct_fed_site():
    d = _load()
    direct = d["sites"][d["sites"]["bsp_id"].isna() & d["sites"]["score"].notna()].iloc[0]["site_id"]
    out = assistant.get_upstream(d["sites"], d["bsps"], d["gsps"], direct)
    assert out["bsp"] is None and out["fed_directly_from_gsp"]


@needs_db
def test_get_siblings_matches_map_panel():
    from backend.main import get_site
    d = _load()
    sid = _site_id("Kingston 11kV")
    out = assistant.get_siblings(d["sites"], sid)
    assert [x["site_id"] for x in out["siblings"]] == [x["site_id"] for x in get_site(sid)["siblings"]]
    assert out["bsp"] == "Kingston Grid" and out["sibling_count"] == 6


@needs_db
def test_search_bsps_matches_pipeline_ranking():
    d = _load()
    out = assistant.search_bsps(d["bsps"], {"rank_by": "stuck_mw", "near": None, "licence_areas": None, "limit": 5})
    stored = d["bsps"].dropna(subset=["stuck_rank"]).sort_values(["stuck_rank", "bsp_id"])
    assert out["total_matches"] == len(stored)
    assert [r["bsp_id"] for r in out["results"]] == stored["bsp_id"].head(5).tolist()
    assert out["results"][0]["name"] == "Northfleet East"


@needs_db
def test_run_tool_dispatches_graph_tools_and_reports_unknown_site():
    d = _load()
    out = assistant.run_tool("get_upstream", {"site_id": "NOPE"}, d["sites"], _site_for_tool, d["bsps"], d["gsps"])
    assert "error" in out


def test_num_rounds_half_up_like_the_web_app():
    assert assistant._num(422.15) == 422.2 and assistant._num(-326.95) == -327.0 and assistant._num(None) is None


def test_prompt_and_tools_name_every_network_covered():
    dnos = [
        {"code": "UKPN", "name": "UK Power Networks", "region": "the South East", "licence_areas": ["LPN", "SPN", "EPN"]},
        {"code": "SPEN", "name": "SP Energy Networks", "region": "Merseyside and North Wales; central and southern Scotland",
         "licence_areas": ["SPM", "SPD"]},
    ]
    prompt = assistant.system_prompt(dnos)
    assert "UK Power Networks (UKPN)" in prompt and "SP Energy Networks (SPEN)" in prompt and "{coverage}" not in prompt
    enums = [t["input_schema"]["properties"]["licence_areas"]["anyOf"][0]["items"]["enum"]
             for t in assistant.tools_for(["LPN", "SPN", "EPN", "SPM", "SPD"])
             if "licence_areas" in t["input_schema"]["properties"]]
    assert enums and all(e == ["EPN", "LPN", "SPD", "SPM", "SPN"] for e in enums)


@needs_db
def test_spain_search_and_municipality_lookup():
    sites = _load()["sites"]
    out = assistant.search_sites(sites, _args(rank_by="stuck_mw", country="ES", limit=3))
    es = sites[(sites["country"] == "ES") & (sites["stuck_mw"] > 0) & sites["score"].notna()]
    assert out["total_matches"] == len(es)
    top = out["results"][0]
    assert top["country"] == "ES" and top["distributor"] and "gsp" not in top
    assert top["stuck_mw"] == assistant._num(es["stuck_mw"].max())
    loc = assistant.run_tool("locate_place", {"name": "Vall d'Alba", "country": "ES"}, sites, lambda _: {})
    assert loc["candidates"][0]["name"] == "Vall d'Alba" and 40 < loc["candidates"][0]["lat"] < 40.3
    assert "castellon" == assistant._fold("Castellón")


def test_prompt_mentions_spain_only_when_covered():
    gb = [{"code": "UKPN", "name": "UK Power Networks", "region": "the South East", "licence_areas": ["LPN"], "country": "GB"}]
    es = gb + [{"code": "ES", "name": "Spain's distribution networks", "region": "Spain", "licence_areas": ["i-DE"],
                "country": "ES", "data_period": "2026-10"}]
    assert "CNMC" not in assistant.system_prompt(gb) and "{spain}" not in assistant.system_prompt(gb)
    p = assistant.system_prompt(es)
    assert "CNMC" in p and "2026-10" in p and "never compare a Spanish score" in p
