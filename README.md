# Grid Intelligence

Map of UK distribution substations scored by "stuck demand": where demand is queuing and published headroom has run out. MVP covers UK Power Networks (LPN, SPN, EPN), demand side only.

## Setup

```bash
uv sync
export UKPN_API_KEY=...            # or put it in a local .env (never committed)
uv run python -m pipeline.download_raw   # raw datasets -> data/raw/*.parquet
uv run python -m pipeline.spike_join     # join / match-rate report
uv run python -m pipeline.profile_raw    # writes data/PROFILE.md
```

## Data sources and licences

All data from the [UK Power Networks Open Data Portal](https://ukpowernetworks.opendatasoft.com/). Contains data from UK Power Networks, licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

| Dataset ID | Used for | Licence |
|---|---|---|
| `grid-and-primary-sites` | substation locations (spine) | CC BY 4.0 |
| `ukpn-dfes-network-headroom-report` | future demand headroom (2030) | CC BY 4.0 |
| `ukpn-ltds-table-3a-load-data-observed` | observed peak demand, firm capacity | CC BY 4.0 |
| `ukpn-capacity-heatmap` | published demand headroom, demand connection offers | CC BY 4.0 |
| `ukpn-grid-supply-points-overview` | GSP limits and utilisation | CC BY 4.0 |
| `ukpn-gsp-insights` | GSP forecast demand (exploratory) | CC BY 4.0 |
| `ukpn-gsp-project-status` | GSP generation queue (exploratory, not scored) | CC BY 4.0 |
| `ukpn-overall-queue-insights` | UKPN-wide queue totals (exploratory) | CC BY 4.0 |

Headroom figures are published firm-capacity headroom and are indicative only — not a guarantee of available capacity.
