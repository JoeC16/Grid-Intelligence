# Grid Intelligence — Build Plan

Goal: demo-ready MVP to show Fuse Energy. Not production. One phase per session. At the end of each phase: stop, summarise what changed, what to check, and tick the phase off here.

## Phase 1 — Data spike (Days 1–2) ✅
- [x] Create .gitignore (.env, .env.*, keep .env.example, data/, *.duckdb, *.duckdb.wal, *.parquet, Python caches/venvs, node_modules/, web/dist/, .vercel/, .DS_Store, .vscode/, .idea/). Create .env.example with blank UKPN_API_KEY= and ANTHROPIC_API_KEY=. Confirm .env is ignored with git check-ignore.
- [x] Set up Python with uv: ukpyn, pandas, duckdb, python-dotenv.
- [x] Using ukpyn and the UKPN_API_KEY env var (check it exists, never print it), download for LPN, SPN, EPN: ukpn-grid-supply-points-overview, dfes-network-headroom-report, ltds-table-3a-load-data-observed, grid and primary substation locations, LTDS capacity heatmap JSON if available. Save raw to data/raw/ as parquet.
- [x] Write data/PROFILE.md: per dataset, row count, columns + types + 2 example values, licence, oddities.
- [x] Find the join between headroom, GSP queue and lat/lon. Report the join, match rate and unmatched rows.
- Done when: the join key is known and the match rate is reported. Paste PROFILE.md into the chat.

## Phase 2 — Normalise (Day 3) ✅
Scoring unit = **primary substation** (the capacity heatmap's substation list), keyed by FLOC. GSP view = primaries rolled up to their GSP.
- [x] Download ukpn-ltds-table-6-interest-connections and ukpn-large-demand-list; add both to docs/PROFILE.md.
- [x] Build pipeline/adapters/base.py (DNOAdapter: fetch_sites, fetch_headroom, fetch_future_headroom, fetch_queue, fetch_large_demand) and adapters/ukpn.py. All UKPN-specific logic (downloads, name matching, GSP crosswalk) lives in ukpn.py.
- [x] normalise.py: common schema (site_id, name, lat, lon, voltage, licence_area, gsp, firm_capacity_mw, demand_headroom_mw, observed_peak_mw, queue_mw, connections_last_year, headroom_2030_mw, source_dataset, source_date) plus per-field provenance.
  - demand_headroom_mw ← capacity heatmap (published headroom). firm_capacity_mw, observed_peak_mw ← LTDS 3a.
  - queue_mw ← LTDS table 6 demand offers (made, not yet accepted + accepted); heatmap offers as fallback; queue_source flag.
  - connections_last_year ← heatmap demand offers accepted (count, past year).
  - headroom_2030_mw ← DFES Holistic Transition (no scenario is marked central); headroom_2030 stored for all four scenarios.
  - Large demand list (GSP-level only) stored as its own table and rolled into the GSP view.
  - GSPs that can't be mapped are flagged and excluded from scoring.
- [x] GSP rollup table: sum queue_mw over primaries per GSP.
- [x] run.py loads everything into data/grid.duckdb in one command.
- [x] Tests for normalise.py with a small fixture.
- Done when: one sites table, one row per primary substation, all signal columns filled or flagged.

## Phase 3 — Score (Day 4) ✅ (revised)
Definitions: docs/SCORING.md and config/weights.yaml.
- [x] v1: queue pressure 30, headroom tightness 25, utilisation 15, recent activity 15, future squeeze 15. Superseded.
- [x] Investor view (default, leads the demo): add stuck_mw = max(queue_mw − demand_headroom_mw, 0) and oversubscription = queue_mw / max(demand_headroom_mw, 1). Weights: stuck_mw 25, oversubscription 20, headroom tightness 15, utilisation 15, recent activity 10, future squeeze 15.
- [x] score.py: percentile-rank each signal across UKPN primaries, weighted sum, 0–100. Score on available signals, flag missing.
- [x] Developer view: not a score. Load size (MW, default 50); keep sites with demand_headroom_mw ≥ load; rank by headroom_after_queue_mw = demand_headroom_mw − queue_mw, highest first.
- [x] docs/SCORING.md explains both views.
- [x] Unit tests with a 5-row fixture.
- Done when: top 20 printed for each view and plausible.
- Big 33 kV boards with lots of stuck MW rank mid-table on the score (Northfleet East 33kV 203rd); answered by the "Most stuck MW" sort (Phase 5). See docs/SCORING.md.

## Phase 4 — Map (Days 5–6) ✅
- [x] FastAPI: /sites (with filters) and /sites/{id}.
- [x] React + Vite + TS + MapLibre + Tailwind: substations coloured by score, filter bar (licence area, voltage, min score), side panel with every signal and its source link.
- Done when: fast and clickable around London.

## Phase 5 — Lenses and sliders (Day 7) ✅
- [x] v1: investor/developer toggle with an inverted weighted developer score. Superseded by the developer definition in Phase 3.
- [x] Weight sliders for the investor view that re-rank live (six revised signals).
- [x] Investor "Rank by: Score | Most stuck MW" sort (stuck_rank: stuck_mw > 0, largest first).
- [x] Developer view: "load size (MW)" input, default 50. Filter to sites with published headroom ≥ load, rank by headroom − queue ahead, re-ranking live as the load changes.
- [x] Ranked list panel for whichever ranking is active; map colour, tooltip and side panel follow it.

## Phase 6 — AI ask box (Days 8–9)
- [x] /query endpoint using the Claude API with tools search_sites(filters) and get_site(id), plus locate_place(name) for place names. Returns ranked sites plus a plain-English why. Only numbers from tools: enforced by prompt, by tools that return every figure (distances included), and by a server-side check that flags any number not found in a tool result.
- [x] Ask panel in the web app: answer, sites ringed on the map and clickable, warning on unverified numbers.
- [ ] Test with 5 questions (scripts/ask_check.py), e.g. "Where could a 50 MW data centre connect fastest within 30 km of Slough?" Blocked: ANTHROPIC_API_KEY isn't reaching the session.
- Done when: answers match the map, no invented numbers.

## Phase 7 — Polish and deploy (Day 10)
- [ ] Attribution footer per licence, "published headroom, not guaranteed" disclaimer.
- [ ] Deploy: frontend on Vercel, API on Fly.io or Railway.
- [ ] README with setup, data sources and licences.
