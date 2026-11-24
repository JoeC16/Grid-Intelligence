"""UK Power Networks adapter (LPN, SPN, EPN).

All UKPN-specific logic lives here: dataset IDs, downloads via ukpyn, column
names, substation name matching and the GSP name crosswalk.

Scoring unit = the substations in the LTDS capacity heatmap (primaries and the
lower busbars of grid sites that feed demand directly). site_id = FLOC.
See docs/PROFILE.md for the evidence behind each join.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
from functools import cache
from pathlib import Path

import pandas as pd

from .. import bronze
from . import ods
from .base import DNOAdapter, DNOInfo, Source

DNO = "UKPN"
PORTAL = "https://ukpowernetworks.opendatasoft.com/explore/dataset/"

SITES_DS = "grid-and-primary-sites"
HEATMAP_DS = "ukpn-capacity-heatmap"
DFES_DS = "ukpn-dfes-network-headroom-report"
LTDS3A_DS = "ukpn-ltds-table-3a-load-data-observed"
LTDS6_DS = "ukpn-ltds-table-6-interest-connections"
GSP_DS = "ukpn-grid-supply-points-overview"
LARGE_DEMAND_DS = "ukpn-large-demand-list"

DATASETS = [
    GSP_DS,
    DFES_DS,
    LTDS3A_DS,
    SITES_DS,
    HEATMAP_DS,
    LTDS6_DS,
    LARGE_DEMAND_DS,
    # exploratory, not used by the pipeline
    "ukpn-gsp-insights",
    "ukpn-gsp-project-status",
    "ukpn-overall-queue-insights",
]

# DFES 2025 scenarios. None is marked as UKPN's central / best view in the
# dataset or its metadata, so we default to Holistic Transition.
DEFAULT_SCENARIO = "Holistic Transition"

# LTDS table 6 statuses that count as queued demand (offered, not connected).
QUEUE_STATUSES = {
    "Connection offers made (not yet accepted by customer)",
    "Connection offers made (accepted by customer)",
}

# Heatmap/LTDS GSP name (normalised, see _gsp_key) -> GSP overview name.
# Each entry is backed by evidence in docs/PROFILE.md.
GSP_ALIASES = {
    "CANTERBURY": "CANTERBURY NORTH",
    "NORTHFLEET": "NORTHFLEET EAST",
    "TILBURY 1&7": "TILBURY SGTS 1&7",
    "TILBURY 2&8": "TILBURY SGTS 2&8",
    "WILLESDEN GRID 66": "WILLESDEN 66",
    # DFES names this group "Barking 132"; site "BARKING 132" has FLOC
    # EPN-S0000000C7139, the same FLOC as overview row "BARKING C (EPN)".
    "BARKING 132 (EPN)": "BARKING C (EPN)",
    # DFES puts all six primaries under "Elstree 9", one of the Elstree
    # groups; the overview has a single ELSTREE (EPN) row.
    "ELSTREE STANMORE (EPN)": "ELSTREE",
}
# Unresolved: "Willesden" (EPN) primaries. Overview only has LPN Willesden 132
# and Willesden 66 and nothing says which one they sit under.
UNMAPPED_GSP_REASON = "GSP unmapped: no matching row in the GSP overview"
UNMAPPED_GSP = "(unmapped)"

# Large demand list technology labels -> common labels.
LARGE_DEMAND_TECH = {"Large Demand": "large_demand", "Distributed Energy Resource": "der"}

# Heatmap BSP name -> DFES grid-level substation name, where the names differ.
# Each is backed by evidence: the grid substation is one of the BSP's own
# children, or the name is a plain abbreviation. Groupings ("Worthing Grid
# Total" = boards A and B) are deliberately not aliased: they stay unmatched.
BSP_ALIASES = {
    "Finsbury Market F 33kV": "Finsbury Mkt F 33kV",
    "Bengeworth Road 33kV": "Bengeworth Rd Grid 33kV",
    "Buckhurst Hill 33kV via Brimsdown": "Buckhurst Hill 33kV",
    "Hackney Grid 66kV Black Bar": "Hackney Grid 66kV",
    "Moscow Road 22kV": "Moscow Rd 22kV",
    "Palmers Green Grid 33": "Palmers Grn Grid 33kV",
    "Palmers Green Grid Total": "Palmers Grn Grid 33kV",
    "Leicester Road 33": "Leicester Rd Grid 33kV",
    "W. Weybridge 132/33": "West Weybridge Grid 33kV",
    "Deptford 22kV": "Deptford West 22kV",
    "Marston Grid 33": "Marston Rd Grid 33kV",
    "Great Yarmouth Grid 33": "GT Yarmouth Grid 33kV",
}

# ---------------------------------------------------------------- download --


async def download_datasets(ids: list[str], out_dir: Path) -> None:
    """Export UKPN datasets via ukpyn into one bronze snapshot (helpers shared in ods.py)."""
    from ukpyn import UKPNClient

    ods.api_key("UKPN_API_KEY")  # fail early, with a clear message
    manifest = ods.Manifest(out_dir)
    async with UKPNClient(timeout=300) as client:
        for ds in ids:
            print(f"Downloading {ds} ...")
            meta = await ods.with_retry(f"{ds} meta", client.get_dataset, ds)
            metas = (meta.model_dump().get("metas") or {}).get("default") or {}
            raw = await ods.with_retry(f"{ds} export", client.export_data, ds, format="json")
            manifest.add(ods.save(pd.DataFrame(json.load(io.BytesIO(raw))), ds, metas, out_dir))


# ----------------------------------------------------------------- helpers --


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def _gsp_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.upper().replace("KV", "")).strip()


def _bsp_key(name: str) -> str:
    """Normalise a BSP / grid substation name: drop kV, voltages and filler words."""
    k = name.lower().replace("kv", "")
    k = re.sub(r"\b\d+(/\d+)?\b", "", k)
    k = re.sub(r"\b(grid|total|group|main|local)\b", "", k)
    return re.sub(r"\s+", " ", k).strip()


def match_gsp(name: str, area: str, overview: set[str]) -> str | None:
    """Map a substation's GSP name + licence area to a GSP-overview name."""
    k = _gsp_key(name)
    stripped = re.sub(r" (132|66|33|22)$", "", k)
    for cand in (k, f"{k} ({area})", stripped, f"{stripped} ({area})"):
        cand = GSP_ALIASES.get(cand, cand)
        if cand in overview:
            return cand
    return None


# ----------------------------------------------------------------- adapter --


INFO = DNOInfo(
    code=DNO,
    name="UK Power Networks",
    region="London, the South East and the East of England",
    licence_areas=("LPN", "SPN", "EPN"),
    portal_name="UK Power Networks Open Data Portal",
    portal_url="https://ukpowernetworks.opendatasoft.com/",
    licence="CC BY 4.0",
    licence_url="https://creativecommons.org/licenses/by/4.0/",
    map_center=(0.35, 51.55),
    map_zoom=7.6,
    min_sites=900,
    fallback_id_prefix="UKPN-MRID-",
)


class UKPNAdapter(DNOAdapter):
    dno = DNO
    info = INFO
    default_scenario = DEFAULT_SCENARIO

    def __init__(self, raw_dir: Path | None = None):
        # Read the latest bronze snapshot unless told otherwise.
        self.raw_dir = raw_dir or bronze.latest(DNO) or bronze.snapshot_dir(DNO)

    @property
    def snapshot_date(self) -> str:
        return self.raw_dir.name

    def snapshot_dates(self) -> list[str]:
        return [p.name for p in bronze.snapshots(DNO)]

    def for_snapshot(self, snapshot_date: str) -> "UKPNAdapter":
        return UKPNAdapter(bronze.BRONZE_ROOT / DNO.lower() / snapshot_date)

    def download(self, refresh: bool = False) -> None:
        """refresh=True takes a new snapshot (today's folder); otherwise fills gaps in the current one."""
        if refresh:
            self.raw_dir = bronze.snapshot_dir(DNO)
            missing = list(DATASETS)
        else:
            missing = [d for d in DATASETS if not (self.raw_dir / f"{d}.parquet").exists()]
        if missing:
            asyncio.run(download_datasets(missing, self.raw_dir))
            self._clear_caches()

    def _clear_caches(self) -> None:
        for name in ("_raw", "_manifest", "_heatmap", "_name_to_floc", "_name_to_site", "_table6"):
            getattr(type(self), name).cache_clear()

    # -- raw access

    @cache
    def _raw(self, dataset_id: str) -> pd.DataFrame:
        return pd.read_parquet(self.raw_dir / f"{dataset_id}.parquet")

    @cache
    def _manifest(self) -> dict:
        return json.loads((self.raw_dir / "_manifest.json").read_text())

    @cache
    def _heatmap(self) -> pd.DataFrame:
        """Heatmap rows with site_id attached. Split sites share a site_id."""
        hm = self._raw(HEATMAP_DS).copy()
        hm["site_id"] = hm["name"].map(_norm).map(self._name_to_floc())
        missing = hm["site_id"].isna()
        hm.loc[missing, "site_id"] = "UKPN-MRID-" + hm.loc[missing, "mrid"]
        return hm

    @cache
    def _name_to_floc(self) -> dict[str, str]:
        """Substation name -> FLOC, from DFES, LTDS 3a, then the sites list."""
        dfes = self._raw(DFES_DS)
        ltds = self._raw(LTDS3A_DS)
        sites = self._raw(SITES_DS)
        lookup: dict[str, str] = {}
        pairs = [
            zip(sites["sitename"], sites["sitefunctionallocation"]),
            zip(ltds["substation"], ltds["functional_location"]),
            zip(dfes["substation_name"], dfes["sitefunctionallocation"]),
        ]
        for pairs_ in pairs:  # later sources win: DFES is the most reliable
            for name, floc in pairs_:
                if isinstance(floc, str):
                    lookup[_norm(name)] = floc
        return lookup

    @cache
    def _name_to_site(self) -> dict[str, str]:
        """Heatmap substation name -> site_id."""
        hm = self._heatmap()
        return dict(zip(hm["name"].map(_norm), hm["site_id"]))

    def _date(self, dataset_id: str) -> str:
        return self._manifest()[dataset_id]["modified"][:10]

    # -- DNOAdapter

    def fetch_sites(self) -> pd.DataFrame:
        hm = self._heatmap()
        overview = set(self._raw(GSP_DS)["gsp"].str.upper())
        hm["gsp_match"] = [match_gsp(g, a, overview) for g, a in zip(hm["gsp"], hm["area"])]
        sites = hm.groupby("site_id", sort=True).agg(
            name=("name", lambda s: " / ".join(sorted(s))),
            lat=("latitude", "mean"),
            lon=("longitude", "mean"),
            voltage_kv=("voltages", "first"),
            licence_area=("area", "first"),
            gsp=("gsp_match", "first"),
        ).reset_index()
        sites["gsp_mapped"] = sites["gsp"].notna()
        sites["exclude_reason"] = sites["gsp_mapped"].map(lambda ok: None if ok else UNMAPPED_GSP_REASON)
        return sites

    def fetch_headroom(self) -> pd.DataFrame:
        hm = self._heatmap()
        published = hm.groupby("site_id")["demandavailablecapacity"].sum(min_count=1)

        # LTDS 3a: per substation, use the binding season (least unutilised
        # capacity), then sum the substations that make up each site.
        ltds = self._raw(LTDS3A_DS).copy()
        ltds["site_id"] = ltds["substation"].map(_norm).map(self._name_to_site())
        ltds = ltds.dropna(subset=["site_id"])
        ltds["util"] = ltds["maximum_demand_24_25_mw"] / ltds["firm_capacity_mw"].where(ltds["firm_capacity_mw"] > 0)
        binding = ltds.sort_values("util", ascending=False, na_position="last").drop_duplicates("substation")
        load = binding.groupby("site_id").agg(
            firm_capacity_mw=("firm_capacity_mw", "sum"),
            observed_peak_mw=("maximum_demand_24_25_mw", "sum"),
        )
        out = load.join(published.rename("demand_headroom_mw"), how="outer").reset_index()
        return out.rename(columns={"index": "site_id"})

    def fetch_future_headroom(self) -> pd.DataFrame:
        dfes = self._raw(DFES_DS)
        dfes = dfes[dfes["category"] == "Demand Headroom"].copy()
        dfes["site_id"] = dfes["substation_name"].map(_norm).map(self._name_to_site())
        dfes = dfes.dropna(subset=["site_id"])
        # Some substation names repeat within a scenario-year; keep one each.
        dfes = dfes.drop_duplicates(["substation_name", "scenario", "year"])
        dfes["year"] = dfes["year"].astype(int)
        out = dfes.groupby(["site_id", "scenario", "year"], as_index=False)["headroom_mw"].sum()
        return out

    @cache
    def _table6(self) -> pd.DataFrame:
        """LTDS table 6 rows with site_id (None if not a heatmap site), queued MW and GSP."""
        t6 = self._raw(LTDS6_DS).copy()
        site_ids = set(self._heatmap()["site_id"])
        t6["site_id"] = t6["substation"].map(_norm).map(self._name_to_site())
        by_floc = t6["site_id"].isna() & t6["sitefunctionallocation"].isin(site_ids)
        t6.loc[by_floc, "site_id"] = t6.loc[by_floc, "sitefunctionallocation"]
        t6["queued_mw"] = t6["demand_numbers_received_total_capacity"].where(
            t6["status_of_connection"].isin(QUEUE_STATUSES), 0.0
        ).fillna(0.0)
        overview = set(self._raw(GSP_DS)["gsp"].str.upper())
        area = t6["licencearea"].str.extract(r"\((\w+)\)")[0]
        t6["gsp"] = [match_gsp(g, a, overview) for g, a in zip(t6["gridsupplypoint"], area)]
        # Fallback: the row's own FLOC is a GSP site in the overview.
        gsp_by_floc = self._raw(GSP_DS).dropna(subset=["floc"]).drop_duplicates("floc")
        gsp_by_floc = dict(zip(gsp_by_floc["floc"], gsp_by_floc["gsp"].str.upper()))
        t6["gsp"] = t6["gsp"].fillna(t6["sitefunctionallocation"].map(gsp_by_floc))
        return t6

    def fetch_gsp_queue(self) -> pd.DataFrame:
        t6 = self._table6()
        grid = t6[t6["site_id"].isna()]
        out = grid.groupby("gsp", dropna=False)["queued_mw"].sum().reset_index()
        out["gsp"] = out["gsp"].fillna(UNMAPPED_GSP)
        return out.rename(columns={"queued_mw": "queue_mw"})

    def fetch_queue(self) -> pd.DataFrame:
        hm = self._heatmap()
        t6 = self._table6().dropna(subset=["site_id"])
        t6_queue = t6.groupby("site_id")["queued_mw"].sum()

        hm["hm_queue"] = hm["loadconnectionoffersmadecapacity"].fillna(0) + hm[
            "loadconnectionoffersacceptedcapacity"
        ].fillna(0)
        hm["hm_has_offers"] = hm[["loadconnectionoffersmadecount", "loadconnectionoffersacceptedcount"]].notna().any(axis=1)
        per_site = hm.groupby("site_id").agg(
            hm_queue=("hm_queue", "sum"),
            hm_has_offers=("hm_has_offers", "any"),
            # Heatmap only lists activity where it happened in the past year,
            # so a missing count means zero.
            connections_last_year=("loadconnectionoffersacceptedcount", lambda s: int(s.fillna(0).sum())),
        )
        per_site["queue_mw"] = t6_queue.reindex(per_site.index)
        per_site["queue_source"] = per_site["queue_mw"].notna().map({True: LTDS6_DS, False: None})
        fallback = per_site["queue_mw"].isna() & per_site["hm_has_offers"]
        per_site.loc[fallback, "queue_mw"] = per_site.loc[fallback, "hm_queue"]
        per_site.loc[fallback, "queue_source"] = HEATMAP_DS
        # In neither dataset: no recorded demand interest.
        none = per_site["queue_mw"].isna()
        per_site.loc[none, "queue_mw"] = 0.0
        per_site.loc[none, "queue_source"] = "none"
        per_site = per_site.reset_index()
        return per_site[["site_id", "queue_mw", "queue_source", "connections_last_year"]]

    def fetch_large_demand(self) -> pd.DataFrame:
        ld = self._raw(LARGE_DEMAND_DS)
        return pd.DataFrame(
            {
                "project_id": ld["anonymised_name"],
                "licence_area": ld["licence_area"],
                "gsp": ld["grid_supply_point"].str.upper(),
                "technology": ld["demand_technology_type"].map(LARGE_DEMAND_TECH),
                "import_capacity_mva": ld["required_import_capacity_kva"] / 1000.0,
                "application_date": pd.to_datetime(ld["application_date"]).dt.date,
            }
        )

    def fetch_gsps(self) -> pd.DataFrame:
        g = self._raw(GSP_DS)
        return pd.DataFrame(
            {
                "gsp": g["gsp"].str.upper(),
                "licence_area": g["dno"],
                "lat": g["geo_point_2d_lat"],
                "lon": g["geo_point_2d_lon"],
                "import_capacity_utilisation_pct": g["import_capacity_utilisation"],
                "technical_limit_rag": g["technical_limits_available"],
            }
        ).drop_duplicates("gsp")

    # -- topology (Phase 8)

    def fetch_topology(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """BSPs from the heatmap's `bsp` field, matched to DFES grid-level substations.

        A matched BSP is almost always also a site on the map (its own 33 kV
        board, for example); its headroom is then that site's published
        headroom, so the same substation never shows two figures. DFES (current
        year, default scenario) is the fallback when the BSP isn't a site.
        """
        hm = self._heatmap()
        dfes = self._raw(DFES_DS)
        grid = dfes[(dfes["category"] == "Demand Headroom") & dfes["physical_level"].isin(["GRID", "COMPARISON_GRID"])]
        by_key = {}
        for name, floc in zip(grid["substation_name"], grid["sitefunctionallocation"]):
            by_key.setdefault(_bsp_key(name), (name, floc))
        year = str(pd.Timestamp.now().year)
        dfes_now = grid[(grid["year"] == year) & (grid["scenario"] == DEFAULT_SCENARIO)].groupby("sitefunctionallocation")["headroom_mw"].sum()
        coords = grid.drop_duplicates("sitefunctionallocation").set_index("sitefunctionallocation")[
            ["spatial_coordinates_lat", "spatial_coordinates_lon"]]

        sites = self.fetch_sites().set_index("site_id")
        site_headroom = self.fetch_headroom().set_index("site_id")["demand_headroom_mw"]

        rows, links = [], []
        for (bsp_name, area), kids in hm.groupby(["bsp", "area"]):
            kid_ids = sorted(set(kids["site_id"]))
            if bsp_name == "Direct":
                links += [(sid, None) for sid in kid_ids]
                continue
            target = by_key.get(_bsp_key(BSP_ALIASES.get(bsp_name, bsp_name)))
            if target:
                floc = target[1]
                bsp_id = f"BSP:{floc}"
                own_site = floc if floc in sites.index else None
                if own_site:
                    headroom, source = site_headroom.get(own_site), HEATMAP_DS
                else:
                    headroom, source = dfes_now.get(floc), DFES_DS
                lat, lon = coords.loc[floc].tolist() if floc in coords.index else (None, None)
                note = None
            else:
                bsp_id = f"BSP:{area}:{bsp_name}"
                own_site, headroom, source = None, None, None
                lat = kids["latitude"].mean()
                lon = kids["longitude"].mean()
                note = "No published headroom found for this BSP (name doesn't match a grid substation)"
            gsps = sites.loc[[k for k in kid_ids if k in sites.index], "gsp"].dropna()
            gsp = sites.at[own_site, "gsp"] if own_site and pd.notna(sites.at[own_site, "gsp"]) else (
                gsps.mode().iloc[0] if len(gsps) else None)
            rows.append({
                "bsp_id": bsp_id, "name": bsp_name, "licence_area": area, "lat": lat, "lon": lon,
                "site_id": own_site, "gsp": gsp,
                "headroom_mw": None if headroom is None or pd.isna(headroom) else float(headroom),
                "headroom_source": source, "matched": target is not None, "note": note,
            })
            links += [(sid, bsp_id) for sid in kid_ids]
        bsps = pd.DataFrame(rows).drop_duplicates("bsp_id")
        link_df = pd.DataFrame(links, columns=["site_id", "bsp_id"]).drop_duplicates("site_id")
        return bsps, link_df

    def sources(self) -> dict[str, Source]:
        def src(ds: str) -> Source:
            return Source(ds, self._date(ds), PORTAL + ds, self._manifest()[ds].get("license") or "")

        hm = src(HEATMAP_DS)
        return {
            "name": hm,
            "lat": hm,
            "lon": hm,
            "voltage": hm,
            "licence_area": hm,
            "gsp": src(GSP_DS),
            "demand_headroom_mw": hm,
            "firm_capacity_mw": src(LTDS3A_DS),
            "observed_peak_mw": src(LTDS3A_DS),
            "queue_mw": src(LTDS6_DS),  # per-row fallback recorded in queue_source
            "grid_level_queue_mw": src(LTDS6_DS),
            "connections_last_year": hm,
            "headroom_2030_mw": src(DFES_DS),
            "large_demand": src(LARGE_DEMAND_DS),
            # Phase 8: BSP headroom is the BSP's own site's published headroom
            # (DFES current year where the BSP isn't a site; per-BSP source in bsps.headroom_source).
            "bsp_headroom_mw": hm,
            "gsp_utilisation": src(GSP_DS),
        }
