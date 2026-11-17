"""Write docs/PROFILE.md from the raw parquet files in data/raw/.

Usage:  uv run python -m pipeline.profile_raw
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "docs" / "PROFILE.md"

PURPOSE = {
    "grid-and-primary-sites": "Spine. One row per grid/primary substation with lat/lon and FLOC.",
    "ukpn-dfes-network-headroom-report": "Future headroom (2024-2050) per substation, 4 DFES scenarios.",
    "ukpn-ltds-table-3a-load-data-observed": "Observed peak demand 24/25, 5-yr forecast, firm capacity.",
    "ukpn-capacity-heatmap": "LTDS heatmap: published demand headroom + demand connection offers/estimates (primaries).",
    "ukpn-ltds-table-6-interest-connections": "LTDS new connection interest per substation x status (demand + generation MW and counts). Main source of queue_mw.",
    "ukpn-large-demand-list": "Live, committed, not-yet-energised demand projects >= 5 MVA (and BESS), anonymised, GSP level. Where data-centre-scale demand shows up.",
    "ukpn-grid-supply-points-overview": "GSP-level observed power flow, asset/technical limits, utilisation.",
    "ukpn-gsp-insights": "Extra. GSP-level forecast demand (MW/MVAr) by regulatory year.",
    "ukpn-gsp-project-status": "Extra. GSP-level connection queue by Gate status — GENERATION technologies only.",
    "ukpn-overall-queue-insights": "Extra. UKPN-wide DER queue totals by status (20 rows).",
}

ODDITIES = {
    "grid-and-primary-sites": [
        "Key: `sitefunctionallocation` (FLOC), unique per row.",
        "1,504 sites but only 1,442 distinct coordinates: grid and primary substations on the same plot share a point.",
        "524 sites have no headroom/load data in DFES or LTDS (220 grid, 304 primary) — mostly 132kV grid nodes and customer/sub-primaries.",
        "`transratingsummer/winter` and `reversepower` are comma-joined strings, one value per transformer.",
        "`maxdemandsummer/winter` null for 527 rows; `datecommissioned` almost always null and uses 2-digit years.",
        "`sitevoltage` is the *highest* voltage (e.g. 33 for a 33/11kV primary); LTDS/DFES name the *lower* busbar (e.g. '11kV').",
    ],
    "ukpn-dfes-network-headroom-report": [
        "Long format: category x scenario x year x substation. 59,280 Demand Headroom rows = 4 scenarios x 15 years x 988.",
        "Scenarios: Counterfactual, Holistic Transition, Electric Engagement, Hydrogen Evolution. Years 2024-2035 annually, then 2040/2045/2050. `year` is a string.",
        "`headroom_percent`, `demand_rag`, `physical_level` only populated for Demand Headroom rows (null for both generation categories).",
        "988 rows per scenario-year but 979 FLOCs: split sites (Purfleet T1&T2/T3&T4, Sundon, Moreton Street) have several `substation_name`s per FLOC, and some names repeat with differing columns. Must aggregate per FLOC in Phase 2.",
        "Negative `headroom_mw` = forecast overload (168 substations negative in 2030 Counterfactual).",
        "`physical_level` mixes GRID (162) and PRIMARY (813) per scenario-year, plus PRIMARY_SUBSET and one COMPARISON_GRID.",
        "180 rows have no coordinates (fine — we take lat/lon from the sites spine).",
    ],
    "ukpn-ltds-table-3a-load-data-observed": [
        "Two rows per substation (Winter, Summer). Key: `functional_location` (FLOC).",
        "980 substations / 976 FLOCs: Sundon, Purfleet, Moreton Street, Steyning have two substations under one FLOC.",
        "`substation_mrid` (CIM id, leading underscore) does NOT match the heatmap `mrid` — different CIM model versions.",
        "`unutilised_capacity_percent` < 0 for 28 rows (peak > firm capacity); 2 rows have firm capacity 0 (and null %).",
        "`minimum_load_scaling_factor` is a '34.3%' string, only on one season row.",
        "Published 2026-06-24 — oldest dataset in the set.",
    ],
    "ukpn-capacity-heatmap": [
        "Primaries only (`type` is always 'Primary'). No FLOC column.",
        "`mrid` doesn't join to LTDS. Exact substation `name` matches DFES `substation_name` for 966/967 rows (miss: 'Kimberley Rd B 11kV').",
        "Demand queue lives here: `loadconnectionoffersmade*`, `loadconnectionoffersaccepted*`, `loadbudgetestimatesprovided*` (count + MW). Null means none (min count is 1, no zeros).",
        "`demandavailablecapacity` is the published demand headroom (MW); 28 rows ≤ 0 (min −5.2). RAG in `demandconstraint`: 937 green, 14 amber, 16 red.",
        "`description` is a generation TIA threshold note, not a description. `voltages` always filled; `voltage` null for 294 rows.",
        "Nearest-neighbour coordinate matching is unreliable (66% agreement with name match) because co-located grid+primary sites share coordinates. Use names.",
    ],
    "ukpn-grid-supply-points-overview": [
        "60 rows, 57 distinct FLOCs. GSPs that straddle licence areas appear twice with '(LPN)/(EPN)/(SPN)' suffixes; HURST (LPN) and HURST (SPN) share one FLOC.",
        "Tilbury split into 'TILBURY SGTs 1&7' / '2&8' with null FLOC, plus a plain 'TILBURY' row no substation maps to.",
        "`asset_import_limit` and `technical_limit_*` are strings containing 'N/A' (36 rows N/A for technical limits).",
        "NO demand queue here. This is capacity/utilisation context only.",
        "GSP names differ from LTDS/DFES/heatmap ('Canterbury' vs 'CANTERBURY NORTH', 'Barking West 33kV' vs 'BARKING WEST (EPN)'): needs a normalised name + licence-area crosswalk.",
    ],
    "ukpn-ltds-table-6-interest-connections": [
        "Published 29 May 2026 (portal modified 2026-09-21). One row per substation x status; four statuses: Budget Estimates Provided, offers made (not yet accepted), offers made (accepted), offers made (cancelled/expired/superseded).",
        "`sitefunctionallocation` null for 290/933 rows; exact substation name recovers 269 of them.",
        "18 duplicate substation x status rows (e.g. 'Barking 132kV GIS' listed once under an EPN FLOC and once with none) — summed.",
        "Covers 563 substations. 129 heatmap sites with demand offers in the past year are absent from table 6, so the two don't agree on who has activity.",
        "59 rows (6,467 MW of interest, all statuses) are at substations outside the heatmap: mostly 132kV grid sites plus a few LV-side boards (King Henrys Walk, Oysterbed Rd, Ridham Grid 11kV). Their queued MW (2,204 MW) is kept as GSP-level `grid_level_queue_mw`.",
        "Demand capacities are float32 noise (e.g. 11.949999809). Round for display.",
    ],
    "ukpn-large-demand-list": [
        "No substation: only licence area + GSP name. GSP names already match the GSP overview except BIGGLESWADE (4 large demand, 3 DER) and LITTLE HORSTED (6 DER), which aren't in the overview.",
        "`required_import_capacity_kva` is rounded and in kVA (convert /1000 to MVA, not MW).",
        "252 'Large Demand' + 244 'Distributed Energy Resource' (BESS). Applications 2009-07-10 to 2025-01-09.",
        "Portal publish date 2025-11-04 despite 'reviewed monthly' — the oldest dataset we use. Flag its date in the UI.",
        "Anonymised IDs ('DER #205') — no way to link to a site.",
    ],
    "ukpn-gsp-insights": ["Long format. Values for 4 measures (GB Peak, GB Min, Access Period, Conn Pt Pk) x MW/MVAr x regulatory year."],
    "ukpn-gsp-project-status": [
        "Generation technologies only (solar, battery, wind, gas, EfW...). Measure is MW or count (#). Not usable for the demand queue signal.",
    ],
    "ukpn-overall-queue-insights": ["UKPN-wide totals only; no site or GSP breakdown."],
}


def example(series: pd.Series) -> str:
    vals = [str(v) for v in series.dropna().unique()[:2]]
    vals = [v if len(v) <= 40 else v[:37] + "..." for v in vals]
    return " · ".join(f"`{v}`" for v in vals).replace("|", "\\|") or "_(all null)_"


def section(dataset_id: str, meta: dict) -> str:
    df = pd.read_parquet(RAW / f"{dataset_id}.parquet")
    lines = [
        f"## {dataset_id}",
        "",
        f"{PURPOSE.get(dataset_id, '')}",
        "",
        f"- Title: {meta.get('title')}",
        f"- Rows: **{len(df):,}** · Columns: {len(df.columns)}",
        f"- Licence: **{meta.get('license')}**",
        f"- Publish date (portal `modified`): {meta.get('modified', '')[:10]} · downloaded {meta.get('downloaded_at', '')[:10]}",
        "",
        "| column | type | nulls | examples |",
        "|---|---|---|---|",
    ]
    for col in df.columns:
        lines.append(f"| `{col}` | {df[col].dtype} | {df[col].isna().sum():,} | {example(df[col])} |")
    lines += ["", "**Oddities**", ""] + [f"- {o}" for o in ODDITIES.get(dataset_id, [])] + [""]
    return "\n".join(lines)


JOIN = """## Join

**Join key: FLOC (functional location), e.g. `EPN-S0000000H7013`.**

| from | to | key | match |
|---|---|---|---|
| DFES headroom | sites (lat/lon) | `sitefunctionallocation` = `sitefunctionallocation` | 978/979 FLOCs (99.9%) |
| LTDS 3a | sites | `functional_location` = `sitefunctionallocation` | 976/976 (100%) |
| LTDS 3a | DFES | FLOC | 974/976 (99.8%) |
| Capacity heatmap | FLOC | exact name in DFES → LTDS → sites list | 967/967 (Kimberley Rd B via the sites list) |
| Heatmap | LTDS | `mrid` = `substation_mrid` | 0/967 — doesn't work |
| LTDS table 6 | heatmap site | exact name, then FLOC | 874/933 rows; the other 59 are grid-level (see below) |
| Large demand list | GSP overview | GSP name | 483/496 rows (BIGGLESWADE, LITTLE HORSTED missing) |
| Substation | GSP overview | normalised GSP name + licence area + aliases | 959/964 sites |

## Pipeline (Phase 2)

Scoring unit = **primary substation**: the 967 capacity-heatmap rows, merged to 964 sites by FLOC (Purfleet, Sundon and Moreton Street are each split into two heatmap rows under one FLOC). 959 scorable.

| field | source | rule |
|---|---|---|
| `demand_headroom_mw` | capacity heatmap `demandavailablecapacity` | published headroom; summed for split sites |
| `firm_capacity_mw`, `observed_peak_mw` | LTDS 3a | binding season (highest peak/firm) per substation, summed per site |
| `queue_mw` | LTDS table 6 | demand MW in "offers made (not yet accepted)" + "offers made (accepted)". Fallback: heatmap demand offers made + accepted (past year). Neither: 0, `queue_source = none` |
| `connections_last_year` | capacity heatmap | demand offers accepted (count). Heatmap only lists sites with activity in the past year, so missing = 0 |
| `headroom_2030_mw` | DFES, Demand Headroom, 2030 | **Holistic Transition**. Also stored: `headroom_2030_<scenario>` for all four, and every year in `headroom_scenarios` |
| GSP `queue_mw` | sites + table 6 | sum of primary `queue_mw` + `grid_level_queue_mw` (table 6 rows at substations outside the heatmap) |
| GSP `large_demand_*`, `der_import_*` | large demand list | count and MVA per GSP |

Heatmap and LTDS 3a firm/peak figures disagree for most sites (different LTDS editions; heatmap firm−max = headroom for only 33%). We take headroom from the heatmap (published figure) and firm/peak from LTDS 3a, so utilisation is computed within one dataset.

**DFES scenarios** in the dataset: Counterfactual, Holistic Transition, Electric Engagement, Hydrogen Evolution. Neither the data nor the metadata marks one as UKPN's central/best view, so Holistic Transition is the default.

## GSP name crosswalk

Resolved with evidence:
- **Barking 132kV (EPN)** → `BARKING C (EPN)`. DFES names the group "Barking 132"; site `BARKING 132` has FLOC `EPN-S0000000C7139`, which is the FLOC of overview row `BARKING C (EPN)`.
- **Elstree Stanmore (EPN)** → `ELSTREE`. DFES puts all six primaries under "Elstree 9", one of its Elstree groups; the overview has one ELSTREE (EPN) row.
- **Willesden Grid 132kV** (table 6, grid level) → `WILLESDEN 132` by FLOC `LPN-S000000003298`.
- Name aliases: Canterbury → CANTERBURY NORTH, Northfleet → NORTHFLEET EAST, Tilbury 1&7 / 2&8 → TILBURY SGTs 1&7 / 2&8.

**Unmapped, excluded from scoring:**

| site_id | name | reason |
|---|---|---|
| EPN-S0000000D8122 | Leicester Rd Grid 33kV | GSP "Willesden" (EPN) |
| EPN-S0000000H8024 | Beresford Av Primary 11kV | GSP "Willesden" (EPN) |
| EPN-S0000000H8045 | Wembley Park 11kV | GSP "Willesden" (EPN) |
| EPN-S0000000H8050 | Bee Primary 11kV | GSP "Willesden" (EPN) |
| EPN-S0000000H8113 | Central Wembley Primary 11kV | GSP "Willesden" (EPN) |

All five sit under BSP "Leicester Road 33". The overview only has LPN rows WILLESDEN 132 and WILLESDEN 66, and nothing in the GSP overview or sites list says which one feeds them. Also unmapped: 1 MW of grid-level queue at 'Barking 132kV GIS' (LPN, FLOC `LPN-S000000003622`, not an overview FLOC).

GSP overview rows with no primaries: GRENDON, TILBURY (plain).

**Remaining gaps in `sites`**
- `EPN-S0000000H8015` Luton St Marys Primary 11kV: not in LTDS 3a → no firm capacity / peak.
- `LPN-S000000000246` Kimberley Rd B 11kV: not in LTDS 3a or DFES (they list 'Kimberley Rd 11kV' only) → no firm, peak or 2030 headroom.
"""


def main() -> None:
    manifest = json.loads((RAW / "_manifest.json").read_text())
    parts = [
        "# Data profile",
        "",
        "Source: UK Power Networks Open Data Portal, via ukpyn. All datasets cover LPN, SPN and EPN.",
        "Generated by `uv run python -m pipeline.profile_raw`. Contains public data from UK Power Networks, licensed under CC BY 4.0.",
        "",
        JOIN,
    ]
    order = list(PURPOSE)
    for dataset_id in order + sorted(set(manifest) - set(order)):
        if dataset_id in manifest:
            parts.append(section(dataset_id, manifest[dataset_id]))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(parts))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
