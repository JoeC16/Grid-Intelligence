"""Phase 1 data spike: test the joins between locations, headroom, load and GSP queue.

Usage:  uv run python -m pipeline.spike_join

Spine = grid-and-primary-sites (one row per substation, has lat/lon), keyed by
FLOC (functional location, e.g. "EPN-S0000000H7013").
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

RAW = Path(__file__).resolve().parent.parent / "data" / "raw"

# Hand aliases where GSP names differ between datasets and GSP overview.
GSP_ALIASES = {
    "CANTERBURY": "CANTERBURY NORTH",
    "NORTHFLEET": "NORTHFLEET EAST",
    "TILBURY 1&7": "TILBURY SGTS 1&7",
    "TILBURY 2&8": "TILBURY SGTS 2&8",
    "WILLESDEN GRID 66": "WILLESDEN 66",
}


def load(name: str) -> pd.DataFrame:
    return pd.read_parquet(RAW / f"{name}.parquet")


def norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def gsp_key(name: str) -> str:
    k = name.upper().replace("KV", "")
    return re.sub(r"\s+", " ", k).strip()


def match_gsp(name: str, area: str, overview_keys: set[str]) -> str | None:
    """Map a site's GSP name (+ licence area) to a GSP-overview 'gsp' value."""
    k = gsp_key(name)
    k = GSP_ALIASES.get(k, k)
    stripped = re.sub(r" (132|66|33|22)$", "", k)
    for cand in (k, f"{k} ({area})", stripped, f"{stripped} ({area})"):
        if cand in overview_keys:
            return cand
    return None


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "0/0"


def main() -> None:
    sites = load("grid-and-primary-sites")
    dfes = load("ukpn-dfes-network-headroom-report")
    ltds = load("ukpn-ltds-table-3a-load-data-observed")
    heat = load("ukpn-capacity-heatmap")
    gsp = load("ukpn-grid-supply-points-overview")

    spine = set(sites.sitefunctionallocation)
    demand = dfes[dfes.category == "Demand Headroom"]
    dfes_flocs = set(demand.sitefunctionallocation)
    ltds_flocs = set(ltds.functional_location)

    print("== 1. DFES demand headroom -> sites (FLOC = sitefunctionallocation)")
    print("  DFES FLOCs found in sites:", pct(len(dfes_flocs & spine), len(dfes_flocs)))
    print("  unmatched:", sorted(dfes_flocs - spine))

    print("== 2. LTDS 3a -> sites (FLOC = functional_location)")
    print("  LTDS FLOCs found in sites:", pct(len(ltds_flocs & spine), len(ltds_flocs)))
    print("  LTDS FLOCs also in DFES:", pct(len(ltds_flocs & dfes_flocs), len(ltds_flocs)))
    print("  in DFES not LTDS:", sorted(dfes_flocs - ltds_flocs))
    print("  in LTDS not DFES:", sorted(ltds_flocs - dfes_flocs))

    print("== 3. Capacity heatmap -> FLOC (via exact substation name in DFES)")
    ltds_mrid = set(ltds.substation_mrid.dropna().str.lstrip("_"))
    print("  heatmap mrid found in LTDS substation_mrid:", pct(len(set(heat.mrid) & ltds_mrid), len(heat)))
    name_to_floc = dict(zip(demand.substation_name.map(norm_name), demand.sitefunctionallocation))
    heat["floc"] = heat.name.map(lambda n: name_to_floc.get(norm_name(n)))
    print("  heatmap rows matched by name:", pct(heat.floc.notna().sum(), len(heat)))
    print("  unmatched:", heat.loc[heat.floc.isna(), "name"].tolist())
    print("  heatmap FLOCs in sites:", pct(heat.floc.dropna().isin(spine).sum(), heat.floc.notna().sum()))

    print("== 4. Site -> GSP overview (GSP name from heatmap/LTDS, + licence area)")
    keys = set(gsp.gsp.str.upper())
    heat["gsp_overview"] = [match_gsp(g, a, keys) for g, a in zip(heat.gsp, heat.area)]
    print("  heatmap primaries matched to a GSP overview row:", pct(heat.gsp_overview.notna().sum(), len(heat)))
    miss = heat.loc[heat.gsp_overview.isna()].groupby(["gsp", "area"]).size()
    print("  unmatched heatmap GSP names (rows):", miss.to_dict())
    ltds["area"] = ltds.licencearea.str.extract(r"\((\w+)\)")
    ltds["gsp_overview"] = [match_gsp(g, a, keys) for g, a in zip(ltds.gridsupplypoint, ltds.area)]
    lt = ltds.drop_duplicates("functional_location")
    print("  LTDS substations matched to a GSP overview row:", pct(lt.gsp_overview.notna().sum(), len(lt)))
    used = set(heat.gsp_overview.dropna()) | set(lt.gsp_overview.dropna())
    print("  GSP overview rows with no substations mapped:", sorted(keys - used))
    print("  GSP overview FLOC in sites:", pct(gsp.floc.isin(spine).sum(), gsp.floc.notna().sum()))

    print("== 5. Combined: substations with location + headroom + load + heatmap queue + GSP")
    heat_flocs = set(heat.floc.dropna())
    gsp_flocs = set(lt.loc[lt.gsp_overview.notna(), "functional_location"]) | set(
        heat.loc[heat.gsp_overview.notna(), "floc"].dropna()
    )
    universe = dfes_flocs | ltds_flocs  # substations UKPN publishes headroom/load for
    full = universe & spine & dfes_flocs & ltds_flocs & gsp_flocs
    print("  universe (in DFES or LTDS):", len(universe))
    print("  with lat/lon:", pct(len(universe & spine), len(universe)))
    print("  + DFES headroom + LTDS load + GSP:", pct(len(full), len(universe)))
    print("  + heatmap (primaries only):", pct(len(full & heat_flocs), len(universe)))
    sites_no_data = spine - universe
    print("  sites in location list with no headroom/load data:", len(sites_no_data),
          sites[sites.sitefunctionallocation.isin(sites_no_data)].groupby("sitetype").size().to_dict())


if __name__ == "__main__":
    main()
