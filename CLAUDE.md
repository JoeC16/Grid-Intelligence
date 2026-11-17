# Grid Intelligence

Map of UK distribution substations scored by "stuck demand": where demand is queuing and headroom has run out. First customer pitch: Fuse Energy (grid owner deciding which networks to buy/expand). Later: data centre and industrial developers.

## Scope (MVP)
- UK Power Networks only: licence areas LPN, SPN, EPN. Demand side only.
- Every DNO sits behind pipeline/adapters/base.py (DNOAdapter). Never hard-code UKPN logic outside adapters/ukpn.py.

## Stack
Python 3.12 + uv, ukpyn, pandas, DuckDB (data/grid.duckdb), FastAPI, React + Vite + TS, MapLibre GL, Tailwind, Claude API (tool use).

## Data rules
- Source: UKPN Open Data Portal via ukpyn. UKPN_API_KEY and ANTHROPIC_API_KEY come from environment variables (set in the Claude Code cloud environment; python-dotenv .env only as a local fallback). Never write keys into any file in the repo. Never commit .env or data/.
- Headroom is firm capacity and indicative. UI must say "published headroom", never "available capacity".
- Every number shown in the UI links back to its dataset ID and publish date.
- Record each dataset's licence in README.md. Attribute per CC BY 4.0 / OGL. Never use the UKPN logo.
- The AI layer may only state numbers returned by its tools. No estimates.

## Scoring
See config/weights.yaml. Signals: queue pressure, headroom tightness, utilisation, recent activity, future squeeze. Percentile-rank each, weighted sum, 0-100. Investor view = score; developer view = inverted headroom and queue.

## Working style
- One phase at a time. Stop at the end of each phase and summarise what changed and what to check.
- Tests for normalise.py and score.py with small fixtures.
- Prefer simple, readable code over clever code.

## Plan
Follow PLAN.md. Do one phase at a time, then stop and tick it off.

