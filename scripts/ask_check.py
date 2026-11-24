"""Phase 6/9 check: ask Claude 8 questions (5 + 3 about the network graph) and check the answers against the map.

Usage:  uv run python -m scripts.ask_check        (needs ANTHROPIC_API_KEY or GRID_ANTHROPIC_API_KEY; makes real, billed API calls)

For each question the expected sites are computed straight from the data with
the same search the map uses. A question passes when:
  - every number in the answer came from a tool result (no unverified numbers),
  - the answer never says "available capacity",
  - the sites it names overlap the expected top sites (where there is an expectation).
"""

from __future__ import annotations

import os
import sys
import time

from backend import assistant
from backend.main import _load, _site_for_tool

def place(name: str) -> dict:
    """Same lookup the AI uses, so expected and actual searches start from the same point."""
    c = assistant.locate_place(name)["candidates"][0]
    return {"lat": c["lat"], "lon": c["lon"]}


def top_ids(sites, n=5, **args):
    base = {k: None for k in ["near", "min_headroom_mw", "licence_areas", "voltages_kv", "gsp",
                              "min_score", "name_contains", "limit"]}
    out = assistant.search_sites(sites, {**base, "limit": n, **args})
    return [r["site_id"] for r in out["results"]]


def main() -> int:
    if not assistant.anthropic_key():
        print(f"No Claude API key ({' or '.join(assistant.KEY_ENV_VARS)}): nothing was asked.")
        return 2
    sites = _load()["sites"]
    slough, chelmsford = place("Slough"), place("Chelmsford")
    bow = sites.loc[sites["name"] == "Bow 11kV", "site_id"].iloc[0]
    d = _load()
    bsps = d["bsps"]
    kingston = sites.loc[sites["name"] == "Kingston 11kV", "site_id"].iloc[0]
    kingston_grid = sites.loc[sites["name"] == "Kingston Grid 33kV", "site_id"].iloc[0]
    kingston_siblings = assistant.get_siblings(sites, kingston)["siblings"]
    top_bsps = assistant.search_bsps(bsps, {"rank_by": "stuck_mw", "near": None, "licence_areas": None, "limit": 3})["results"]
    kg_up = assistant.get_upstream(sites, bsps, d["gsps"], kingston_grid)
    # (question, expected site_ids, words the answer must contain)
    questions = [
        ("Where could a 50 MW data centre connect fastest within 30 km of Slough?",
         top_ids(sites, rank_by="effective_headroom", min_headroom_mw=50, near={**slough, "radius_km": 30})),
        ("Which substations have the most demand stuck in the queue?",
         top_ids(sites, rank_by="stuck_mw")),
        ("What are the five most constrained primary substations in London (LPN)?",
         top_ids(sites, rank_by="score", licence_areas=["LPN"])),
        ("Is there room for a 20 MW load within 20 km of Chelmsford?",
         top_ids(sites, rank_by="effective_headroom", min_headroom_mw=20, near={**chelmsford, "radius_km": 20})),
        ("Why does Bow 11kV score so high?", [bow]),
        # Phase 9: relationship questions, checked against graph.py's own answers
        ("What else shares Kingston 11kV's supply?", [x["site_id"] for x in kingston_siblings[:5]], ["Kingston Grid"]),
        ("Which bulk supply points have the most stuck demand?",
         [b["own_board_site_id"] for b in top_bsps if b["own_board_site_id"]], [top_bsps[0]["name"]]),
        ("Is Kingston Grid 33kV's headroom limited upstream?", [kingston_grid],
         [f"{kg_up['effective_headroom_mw']:.1f}"]),
    ]
    questions = [q if len(q) == 3 else (*q, []) for q in questions]
    passed = 0
    for q, expected, must_mention in questions:
        t0 = time.time()
        a = assistant.ask(q, sites, _site_for_tool, bsps=bsps, gsps=d["gsps"])
        took = time.time() - t0
        overlap = set(a.site_ids) & set(expected)
        ok_numbers = not a.unverified_numbers
        ok_terms = "available capacity" not in a.answer.lower()
        ok_sites = bool(overlap) or not expected
        missing = [w for w in must_mention if w.lower() not in a.answer.lower()]
        ok = ok_numbers and ok_terms and ok_sites and not missing
        passed += ok
        print("=" * 100)
        print(f"Q: {q}   [{'PASS' if ok else 'FAIL'}, {took:.0f}s, {a.model}, stop={a.stop_reason}]")
        print(f"tools: {[c['name'] for c in a.tool_calls]}")
        print(a.answer)
        print(f"-> sites named: {a.site_ids}")
        print(f"-> expected top: {expected}  overlap: {sorted(overlap)}")
        print(f"-> unverified numbers: {a.unverified_numbers or 'none'}   'available capacity' used: {not ok_terms}")
        if must_mention:
            print(f"-> must mention {must_mention}: {'missing ' + str(missing) if missing else 'yes'}")
    print("=" * 100)
    print(f"{passed}/{len(questions)} passed")
    return 0 if passed == len(questions) else 1


if __name__ == "__main__":
    sys.exit(main())
