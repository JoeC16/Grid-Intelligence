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

## Phase 6 — AI ask box (Days 8–9) ✅
- [x] /query endpoint using the Claude API with tools search_sites(filters) and get_site(id), plus locate_place(name) for place names. Returns ranked sites plus a plain-English why. Only numbers from tools: enforced by prompt, by tools that return every figure (distances included), and by a server-side check that flags any number not found in a tool result.
- [x] Ask panel in the web app: answer, sites ringed on the map and clickable, warning on unverified numbers.
- [x] Test with 5 questions (scripts/ask_check.py), e.g. "Where could a 50 MW data centre connect fastest within 30 km of Slough?" All 5 name the expected sites, every number traced to a tool result, "published headroom" throughout. (Key supplied as GRID_ANTHROPIC_API_KEY: the cloud environment doesn't pass ANTHROPIC_* to sessions.)
- Done when: answers match the map, no invented numbers.

## Phase 7 — Polish and deploy (Day 10) ✅
- [x] Attribution footer per licence (UKPN CC BY 4.0 with changes stated, OS Open Names OGL v3, OpenStreetMap), "published headroom, not guaranteed" disclaimer, and a Sources & licences dialog listing every dataset with publish date and licence.
- [x] Deploy: frontend and API together on Vercel (one FastAPI app, app.py) instead of Vercel + Fly.io/Railway. Live: https://grid-intelligence-psi.vercel.app. ANTHROPIC_API_KEY to be added in Vercel for the Ask box.
- [x] README with setup, deploy, data sources and licences.

## Phase 8 — Network graph: upstream constraints ✅
Model the network as a tree, GSP → BSP → primary, and let constraints flow through it. A primary can show published headroom while the bulk supply point (BSP) above it is already full; the map should say so.

What the data supports (checked):
- Every primary in the capacity heatmap names its BSP and GSP; DFES agrees on the BSP for 99.9%.
- BSP headroom: DFES publishes headroom for 163 grid-level substations. 150 of 173 BSP names match one of them after normalising ("Grid", "132/33", "Total" etc.), covering 804 of 873 BSP-fed primaries. The other 23 are abbreviations or groupings ("GT Yarmouth", "Finsbury Mkt", "Bow Total") and need an alias list in adapters/ukpn.py.
- 94 primaries are "Direct": fed straight from the GSP (no BSP).
- GSPs have no MW headroom figure; the GSP overview gives import utilisation % and a technical-limit RAG. Use those as flags, not as a MW limit.

Tasks:
- [x] DNOAdapter gains fetch_topology(): nodes (GSP, BSP, primary) and edges (primary → BSP → GSP; Direct primaries → GSP), with each node's published headroom and source. UKPN name matching and aliases stay in adapters/ukpn.py.
- [x] graph.py (DNO-agnostic): build the tree, roll up children's queue and stuck MW to each BSP and GSP, and compute per primary:
  - bsp_headroom_after_queue_mw = BSP published headroom − Σ queue of the primaries under it
  - effective_headroom_mw = min(primary headroom after queue, BSP headroom after queue)
  - upstream_constrained = the BSP is the tighter limit; gsp_flag = GSP technical limit RED or high utilisation
  - Unmatched BSPs flagged (effective headroom = primary only, with a note), never guessed.
- [x] DuckDB tables: nodes, edges, bsp_rollup, gsp_rollup; new columns on sites.
- [x] Developer view: filter and rank on effective (upstream-aware) headroom by default, with a toggle to ignore upstream limits. Investor score unchanged; upstream shown alongside it (see open questions).
- [x] Investor view: "Rank by" gains BSPs by stuck MW (rolled up).
- [x] UI: BSP nodes on the map with faint lines to their primaries when a site is selected; side panel "Upstream" section showing the path primary → BSP → GSP with each level's headroom, queue and sources; "Same BSP" list of sibling primaries.
- [x] docs/PROFILE.md: topology join coverage and unmatched BSPs. docs/SCORING.md: effective headroom.
- [x] Tests for graph.py with a small fixture (two BSPs, one Direct primary, one unmatched BSP).
- Done when: every scorable primary has an upstream path or a flag saying why not; the developer shortlist accounts for BSP limits; the side panel shows the path with sources; coverage is reported.

Decisions taken:
1. BSP headroom = the BSP's own site's published headroom (157 of 158 matched BSPs are sites); DFES current year only as fallback. Changed from "DFES 2026" because that would show two different figures for one substation.
2. Developer view counts BSP limits by default; "Count BSP limits" toggle turns it off.
3. Investor score unchanged; upstream shown alongside, plus a "BSPs" ranking.
4. GSP flag = published import utilisation ≥ 100%. The GSP technical-limits RAG means "limits agreed with NESO yet", not a constraint, so it isn't used as one.

## Phase 9 — Graph for the AI ask box
Expose the same tree to the Ask box so it can answer relationship questions and cite the path. The graph is small (~1.2k nodes), so tools over the DuckDB tables are enough; no graph database.
- [ ] Tools: get_upstream(site_id) (path with headroom and queue at each level), get_siblings(site_id) (primaries on the same BSP), search_bsps(rank_by) (stuck MW, headroom after queue).
- [ ] Prompt: explain upstream limits in plain words; numbers only from tools (existing check covers the new tools).
- [ ] Extend scripts/ask_check.py with three relationship questions, e.g. "What else shares Bow's supply?", "Which BSPs have the most stuck demand?", "Is Kingston's headroom limited upstream?", checked against graph.py's own answers.
- Done when: relationship answers match the map's Upstream panel, no invented numbers.
