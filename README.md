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
uv run uvicorn api.main:app --port 8000     # API: /meta, /sites, /sites/{id}
cd web && npm install && npm run dev        # http://localhost:5173
```

`data/grid.duckdb` tables: `sites` (one row per primary substation), `gsps` (primaries rolled up to GSP, plus grid-level queue and large demand), `headroom_scenarios` (DFES headroom, all scenarios and years), `large_demand`, `field_sources` (dataset ID + publish date for every field), `site_scores` (0–100 stuck-demand score, rank and per-signal percentiles), `score_weights`.

Scoring ([docs/SCORING.md](docs/SCORING.md), config in `config/weights.yaml`):

- **Investor** (`score`, `rank`): stuck-demand score, 0–100. Six percentile-ranked signals (stuck MW, oversubscription, headroom tightness, utilisation, recent activity, future squeeze), weighted. Sites missing a signal are scored on the rest and flagged in `score_missing`.
- **Developer** (`developer_rank`): not a score. Sites with published headroom ≥ a load size (default 50 MW), ranked by headroom left after the queue.

The web app repeats the investor maths in the browser (`web/src/scoring.ts`, kept in step with `pipeline/score.py`) so weight sliders re-rank live.

See [docs/PROFILE.md](docs/PROFILE.md) for every dataset's columns, quirks, and how the joins work.

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

Headroom figures are published firm-capacity headroom and are indicative only — not a guarantee of available capacity.
