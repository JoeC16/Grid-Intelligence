# Grid Intelligence

Map of UK distribution substations scored by "stuck demand": where demand is queuing and published headroom has run out. MVP covers UK Power Networks (LPN, SPN, EPN), demand side only.

## Setup

```bash
uv sync
export UKPN_API_KEY=...            # or put it in a local .env (never committed)
uv run python -m pipeline.run            # download missing raw data, build + score data/grid.duckdb
uv run python -m pipeline.score          # re-score only (after editing config/weights.yaml)
uv run python -m pipeline.run --refresh  # re-download everything first
uv run python -m pipeline.profile_raw    # regenerate docs/PROFILE.md
uv run pytest
```

Run the map locally (two terminals):

```bash
uv run uvicorn backend.main:app --port 8000     # API: /meta, /sites, /sites/{id}
cd web && npm install && npm run dev        # http://localhost:5173
```

AI ask box (`POST /query`): needs a Claude API key in the environment as `ANTHROPIC_API_KEY`, or as `GRID_ANTHROPIC_API_KEY` in the Claude Code cloud environment (which doesn't pass `ANTHROPIC_*` variables through to sessions) (a local `.env` works as a fallback; never commit it). Claude (`claude-opus-5-5`) answers with three tools: `search_sites`, `get_site` and `locate_place`. It may state only numbers its tools returned; any number in an answer that can't be matched to a tool result is listed in `unverified_numbers` and shown as a warning. Check it end to end with `uv run python -m scripts.ask_check` (5 questions, real billed API calls).

`data/grid.duckdb` tables: `sites` (one row per primary substation), `gsps` (primaries rolled up to GSP, plus grid-level queue and large demand), `headroom_scenarios` (DFES headroom, all scenarios and years), `large_demand`, `field_sources` (dataset ID + publish date for every field), `site_scores` (0–100 stuck-demand score, rank and per-signal percentiles), `score_weights`.

Scoring ([docs/SCORING.md](docs/SCORING.md), config in `config/weights.yaml`):

- **Investor** (`score`, `rank`): stuck-demand score, 0–100. Six percentile-ranked signals (stuck MW, oversubscription, headroom tightness, utilisation, recent activity, future squeeze), weighted. Sites missing a signal are scored on the rest and flagged in `score_missing`. Alternative sort: most stuck MW (`stuck_rank`).
- **Developer** (`developer_rank`): not a score. Sites with published headroom ≥ a load size (default 50 MW), ranked by headroom left after the queue.

The web app repeats the investor maths in the browser (`web/src/scoring.ts`, kept in step with `pipeline/score.py`) so weight sliders, the stuck-MW sort and the developer load size re-rank live.

See [docs/PROFILE.md](docs/PROFILE.md) for every dataset's columns, quirks, and how the joins work.

## Deploy (Vercel)

One Vercel project serves both: `app.py` mounts the API at `/api` and serves the built web app at `/`. Vercel detects `app.py` as a FastAPI app; `vercel.json` ships `data/grid.duckdb`, `config/` and `web/dist/` with the function.

`data/` is never committed, so deploy from a machine that has built it:

```bash
uv run python -m pipeline.run          # builds data/grid.duckdb
cd web && npm run build && cd ..       # builds web/dist
vercel deploy --prod                   # uploads per .vercelignore (includes the .duckdb and dist)
```

In the Vercel project settings, add `ANTHROPIC_API_KEY` (Environment Variables) for the AI ask box. Everything else works without it.

To run the production setup locally: `uv run uvicorn app:app --port 8000` after building both.

## Data sources and licences

All data from the [UK Power Networks Open Data Portal](https://ukpowernetworks.opendatasoft.com/). Contains data from UK Power Networks, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

| Dataset ID | Used for | Licence |
|---|---|---|
| `grid-and-primary-sites` | substation names and FLOCs (name matching) | CC BY 4.0 |
| `ukpn-dfes-network-headroom-report` | 2030 demand headroom, all DFES scenarios | CC BY 4.0 |
| `ukpn-ltds-table-3a-load-data-observed` | observed peak demand, firm capacity | CC BY 4.0 |
| `ukpn-capacity-heatmap` | substation list, published demand headroom, connections in the past year | CC BY 4.0 |
| `ukpn-ltds-table-6-interest-connections` | demand queue (offers made / accepted) | CC BY 4.0 |
| `ukpn-large-demand-list` | large committed demand projects per GSP | CC BY 4.0 |
| `ukpn-grid-supply-points-overview` | GSP list, limits and utilisation | CC BY 4.0 |
| `ukpn-gsp-insights` | GSP forecast demand (exploratory) | CC BY 4.0 |
| `ukpn-gsp-project-status` | GSP generation queue (exploratory, not scored) | CC BY 4.0 |
| `ukpn-overall-queue-insights` | UKPN-wide queue totals (exploratory) | CC BY 4.0 |

Place names in the AI ask box are located with **OS Open Names** via [postcodes.io](https://postcodes.io/): contains OS data © Crown copyright and database right, licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Only the place name is sent.

Headroom figures are published firm-capacity headroom and are indicative only — not a guarantee of available capacity.
