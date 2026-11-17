# Grid Intelligence — Build Plan

Goal: demo-ready MVP to show Fuse Energy. Not production. One phase per session. At the end of each phase: stop, summarise what changed, what to check, and tick the phase off here.

## Phase 1 — Data spike (Days 1–2) ✅
- [x] Create .gitignore (.env, .env.*, keep .env.example, data/, *.duckdb, *.duckdb.wal, *.parquet, Python caches/venvs, node_modules/, web/dist/, .vercel/, .DS_Store, .vscode/, .idea/). Create .env.example with blank UKPN_API_KEY= and ANTHROPIC_API_KEY=. Confirm .env is ignored with git check-ignore.
- [x] Set up Python with uv: ukpyn, pandas, duckdb, python-dotenv.
- [x] Using ukpyn and the UKPN_API_KEY env var (check it exists, never print it), download for LPN, SPN, EPN: ukpn-grid-supply-points-overview, dfes-network-headroom-report, ltds-table-3a-load-data-observed, grid and primary substation locations, LTDS capacity heatmap JSON if available. Save raw to data/raw/ as parquet.
- [x] Write data/PROFILE.md: per dataset, row count, columns + types + 2 example values, licence, oddities.
- [x] Find the join between headroom, GSP queue and lat/lon. Report the join, match rate and unmatched rows.
- Done when: the join key is known and the match rate is reported. Paste PROFILE.md into the chat.

## Phase 2 — Normalise (Day 3)
- [ ] Build pipeline/adapters/base.py (DNOAdapter: fetch_sites, fetch_headroom, fetch_queue) and adapters/ukpn.py.
- [ ] normalise.py: common schema (site_id, name, lat, lon, voltage, licence_area, gsp, firm_capacity_mw, demand_headroom_mw, observed_peak_mw, queue_mw, connections_last_year, headroom_2030_mw, source_dataset, source_date).
- [ ] run.py loads everything into data/grid.duckdb in one command.
- Done when: one sites table, one row per substation, all signal columns filled or flagged.

## Phase 3 — Score (Day 4)
- [ ] config/weights.yaml: queue pressure 30, headroom tightness 25, utilisation 15, recent activity 15, future squeeze 15.
- [ ] score.py: percentile-rank each signal across UKPN, weighted sum, 0–100. Score on available signals, flag missing.
- [ ] Unit tests with a 5-row fixture.
- Done when: top 20 printed and plausible.

## Phase 4 — Map (Days 5–6)
- [ ] FastAPI: /sites (with filters) and /sites/{id}.
- [ ] React + Vite + TS + MapLibre + Tailwind: substations coloured by score, filter bar (licence area, voltage, min score), side panel with every signal and its source link.
- Done when: fast and clickable around London.

## Phase 5 — Lenses and sliders (Day 7)
- [ ] Toggle: Investor view (score) vs Developer view (inverted headroom and queue).
- [ ] Weight sliders that re-rank live.

## Phase 6 — AI ask box (Days 8–9)
- [ ] /query endpoint using the Claude API with tools search_sites(filters) and get_site(id). Returns ranked sites plus a plain-English why. Only numbers from tools.
- [ ] Test with 5 questions, e.g. "Where could a 50 MW data centre connect fastest within 30 km of Slough?"
- Done when: answers match the map, no invented numbers.

## Phase 7 — Polish and deploy (Day 10)
- [ ] Attribution footer per licence, "published headroom, not guaranteed" disclaimer.
- [ ] Deploy: frontend on Vercel, API on Fly.io or Railway.
- [ ] README with setup, data sources and licences.
