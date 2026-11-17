"""Phase 1 data spike: write data/PROFILE.md from the raw parquet files.

Usage:  uv run python -m pipeline.profile_raw
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data"
RAW = DATA / "raw"

PURPOSE = {
    "grid-and-primary-sites": "Spine. One row per grid/primary substation with lat/lon and FLOC.",
    "ukpn-dfes-network-headroom-report": "Future headroom (2024-2050) per substation, 4 DFES scenarios.",
    "ukpn-ltds-table-3a-load-data-observed": "Observed peak demand 24/25, 5-yr forecast, firm capacity.",
    "ukpn-capacity-heatmap": "LTDS heatmap: published demand headroom + demand connection offers/estimates (primaries).",
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
| Capacity heatmap | DFES → FLOC | exact `name` = `substation_name` | 966/967 (99.9%) |
| Heatmap | LTDS | `mrid` = `substation_mrid` | 0/967 — doesn't work |
| Substation | GSP overview | normalised GSP name + licence area | heatmap 952/967 (98.4%), LTDS 961/976 (98.5%) |

Whole universe = 981 substations that appear in DFES or LTDS:
- 980/981 (99.9%) have lat/lon
- 959/981 (97.8%) have location + DFES headroom + LTDS load + GSP
- 944/981 (96.2%) also have heatmap demand-queue data (heatmap covers primaries only, so grid substations miss out by design)

**Unmatched rows**
- `EPN-S0000000H8015`: in DFES, not in sites or LTDS. No location.
- In DFES not LTDS: `LPN-S000000000615`, `SPN-S000000008480`, `SPN-S000000008546`, `SPN-S000000009112` (plus H8015).
- In LTDS not DFES: `LPN-S000000000687`, `SPN-S000000009912`.
- Heatmap: 'Kimberley Rd B 11kV' has no name match.
- GSP names that won't map: 'Barking 132kV' (EPN, 4 primaries), 'Elstree Stanmore' (EPN, 6), 'Willesden' (EPN, 5). Need a manual decision in Phase 2.
- GSP overview rows with no substations: BARKING C (EPN), GRENDON, TILBURY.

**What this means for Phase 2**
- `site_id` = FLOC. Spine = grid-and-primary-sites, filtered to the 981 FLOCs with headroom/load data.
- `firm_capacity_mw`, `observed_peak_mw` ← LTDS 3a (take winter or max of seasons; aggregate split sites).
- `demand_headroom_mw` ← heatmap `demandavailablecapacity` (published headroom) for primaries; DFES current year for grid sites.
- `headroom_2030_mw` ← DFES Demand Headroom, 2030 (scenario choice needed; suggest Counterfactual or a scenario mean).
- `queue_mw` ← heatmap load offers made + accepted (+ budget estimates?). Primaries only; grid sites will be flagged missing.
- `connections_last_year` ← no direct dataset yet. Heatmap accepted-offer count is the nearest proxy; worth checking `ukpn-ltds-table-6-interest-connections` and `ukpn-large-demand-list` in Phase 2.
- The GSP overview does not carry a demand queue — the GSP-level queue datasets (`ukpn-gsp-project-status`) are generation-only.
"""


def main() -> None:
    manifest = json.loads((RAW / "_manifest.json").read_text())
    parts = [
        "# Raw data profile (Phase 1)",
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
    (DATA / "PROFILE.md").write_text("\n".join(parts))
    print(f"wrote {DATA / 'PROFILE.md'}")


if __name__ == "__main__":
    main()
