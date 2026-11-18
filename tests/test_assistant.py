"""AI ask box: tools, number verification and the tool loop. No real model calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import assistant
from api.main import DB_PATH, _load, _site_for_tool, app

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


def test_negative_and_thousands():
    tools = [json.dumps({"x": -3.1, "y": 1234.5})]
    assert assistant.verify_numbers("−3.1 MW and 1,234.5 MW", tools, "q") == []


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
    base = {k: None for k in ["near", "min_headroom_mw", "licence_areas", "voltages_kv", "gsp",
                              "min_score", "name_contains", "limit"]}
    return {**base, **kw}


@needs_db
def test_search_by_score_matches_map_ranking():
    out = assistant.search_sites(_load()["sites"], _args(rank_by="score", limit=3))
    first = out["results"][0]
    assert first["name"] == "Bow 11kV" and first["result_rank"] == 1 and first["score_rank_ukpn"] == 1
    assert out["total_matches"] == 959


@needs_db
def test_search_developer_matches_pipeline():
    sites = _load()["sites"]
    out = assistant.search_sites(sites, _args(rank_by="headroom_after_queue", min_headroom_mw=50, limit=25))
    assert out["total_matches"] == int(sites["developer_rank"].notna().sum())
    for r in out["results"]:
        stored = sites.loc[sites.site_id == r["site_id"], "developer_rank"].iloc[0]
        assert r["result_rank"] == stored


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


def test_query_without_key_is_503(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = TestClient(app).post("/query", json={"question": "Where is demand stuck?"})
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
