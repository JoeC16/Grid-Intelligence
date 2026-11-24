# Data model

Grid Intelligence keeps its data in three layers ("medallion"): **bronze** (raw,
as downloaded), **silver** (cleaned, joined, with history) and **gold** (what the
app shows). Everything is rebuilt by one command:

```bash
uv run python -m pipeline.run            # build from the latest bronze snapshot
uv run python -m pipeline.run --refresh  # take a new bronze snapshot first
```

```
DNO open data portals (OpenDataSoft)
        │  adapters/<dno>.py  (UKPN via ukpyn; others via adapters/ods.py)
        ▼
BRONZE  data/bronze/<dno>/<YYYY-MM-DD>/*.parquet + _manifest.json    one folder per DNO per snapshot, never edited
        │  adapters/<dno>.py → normalise.py → graph.py → score.py  (scored nationally: all DNOs together)
        ▼
SILVER  silver.sites / bsps / gsps   (one row per entity per snapshot)
        silver.nodes / edges         (the network graph, with source datasets)
        │  medallion.py
        ▼
GOLD    sites, bsps, gsps, site_scores …   (current figures; the API and map read these)
        gold.site_mart / bsp_mart / gsp_mart, headroom_timeline, large_demand_by_year, changes
        │  backend/main.py, backend/story.py, backend/assistant.py
        ▼
Map · side panel · rankings · Story · Ask box
```

All of it lives in `data/` (never committed). Code: [`pipeline/bronze.py`](../pipeline/bronze.py),
[`pipeline/medallion.py`](../pipeline/medallion.py), [`pipeline/run.py`](../pipeline/run.py).

## Bronze

| What | Where |
|---|---|
| Raw datasets, exactly as exported by the portal (nested fields flattened to columns) | `data/bronze/<dno>/<snapshot>/<dataset_id>.parquet` |
| Per dataset: title, licence, portal publish date (`modified`), row count, download time | `…/<snapshot>/_manifest.json` |

A refresh writes a new dated folder; earlier snapshots are kept. Adapters read
the latest snapshot unless asked for another (`adapter.for_snapshot(date)`).
Snapshots so far: 2026-11-17 and 2026-11-23. No dataset was republished between
them (same publish dates and row counts), so nothing moved.

## Silver

Conformed entities: one ID per thing, the same columns for every DNO, and the
snapshot each row came from.

| Table | Grain | Key columns |
|---|---|---|
| `silver.sites` | site × snapshot | site_id (FLOC), name, licence_area, gsp, bsp_id, published headroom, queue, effective headroom, score, stuck MW, `snapshot_date` |
| `silver.bsps` | BSP × snapshot | bsp_id, gsp, matched, headroom, queue under it, stuck MW, `snapshot_date` |
| `silver.gsps` | GSP × snapshot | gsp, queue (primary + grid level), large demand, import utilisation, `snapshot_date` |
| `silver.nodes` | node | node_id (`GSP:…`, `BSP:…`, or a site FLOC), level, name, lat/lon, `source_dataset` |
| `silver.edges` | edge | child_id → parent_id, kind (`site`, `bsp`) |

Every silver snapshot is rebuilt from its own bronze folder with the current
code, so history stays comparable when the method changes. Every table carries
a `dno` column; each DNO keeps its own snapshot dates.

## Gold

What the app reads. The unqualified tables are the current figures (latest
snapshot); `gold.*` are marts built on them.

| Table | What it answers |
|---|---|
| `sites`, `site_scores` | Every site's signals, investor score, stuck MW, developer ranks, upstream columns (docs/SCORING.md) |
| `bsps`, `gsps`, `edges` | The network tree and roll-ups |
| `headroom_scenarios` | DFES published headroom per site, every scenario and year |
| `large_demand` | Large committed demand projects (GSP level) |
| `field_sources` | Every field → DNO, dataset ID, publish date, licence, URL |
| `dnos` | One row per network operator covered: name, region, licence areas, portal, licence, map view, check thresholds (from each adapter's `DNOInfo`). The app takes every DNO name and attribution from here. |
| `gold.site_mart` | Site level: score, stuck MW, effective headroom, limiting level, **runs-out year** |
| `gold.bsp_mart` | BSP level: the same measures + sites limited by the BSP, its own runs-out year, earliest under it |
| `gold.gsp_mart` | GSP level: queue, **stuck MW** (its BSPs' stuck MW + directly fed primaries'), sites limited upstream, sites running out by 2030, earliest runs-out year, large demand, import utilisation |
| `gold.headroom_timeline` | Per scenario and forecast year: primaries below zero, total published headroom |
| `gold.large_demand_by_year` | Large demand projects and MVA per GSP, technology and application year |
| `gold.changes` | Latest vs previous snapshot: every measure that moved, per site and BSP (empty until a dataset is republished) |

Definitions:
- **Runs-out year**: the first DFES forecast year, from the snapshot's year on, in which a primary's published headroom (default scenario) is below zero. Empty = stays at or above zero to 2050.
- **Stuck MW at a GSP**: GSPs publish no MW headroom, so this is the sum of stuck demand at its BSPs (queue under the BSP beyond its published headroom) and at primaries fed directly from the GSP.
- **Large demand by year**: the list holds only projects still waiting to connect, so older applications drop out as they connect. It shows the backlog's age, not a growth rate.

## How a number reaches the screen

Example: "Northfleet East: 332.0 MW stuck" in the Story.

1. **Bronze**: `ukpn-capacity-heatmap` gives each primary's published headroom and its BSP name; `ukpn-ltds-table-6-interest-connections` gives the demand queue (snapshot 2026-11-23).
2. **Silver**: `normalise.py` builds one row per site; `graph.py` hangs each site off its BSP and GSP and sums the queue under each BSP.
3. **Gold**: `medallion.gsp_mart` adds the stuck MW of Northfleet East's BSPs and of the primaries fed directly from it.
4. **Screen**: `backend/story.py` reads `gold.gsp_mart` and writes the sentence; the chapter lists both datasets with their publish dates.

Nothing in the story, the side panel or the Ask box is typed in by hand: each
figure is computed from these tables, and each links to its dataset and date.
