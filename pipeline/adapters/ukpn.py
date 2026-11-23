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
import os
import re
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

import pandas as pd

from .base import DNOAdapter, Source

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw"
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

RETRIES = 6


# ---------------------------------------------------------------- download --


async def _with_retry(label, fn, *args, **kwargs):
    """The egress path to the portal drops connections intermittently."""
    for attempt in range(1, RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry anything
            if attempt == RETRIES:
                raise
            wait = 2**attempt
            print(f"  {label}: {type(exc).__name__}, retry {attempt}/{RETRIES - 1} in {wait}s")
            await asyncio.sleep(wait)


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Turn nested dict/list columns into flat columns parquet can store."""
    for col in list(df.columns):
        sample = df[col].dropna()
        if sample.empty:
            continue
        first = sample.iloc[0]
        if isinstance(first, dict):
            if {"lat", "lon"} <= set(first):
                df[f"{col}_lat"] = df[col].map(lambda v: v.get("lat") if isinstance(v, dict) else None)
                df[f"{col}_lon"] = df[col].map(lambda v: v.get("lon") if isinstance(v, dict) else None)
            df[col] = df[col].map(lambda v: json.dumps(v) if v is not None else None)
        elif isinstance(first, list):
            df[col] = df[col].map(lambda v: json.dumps(v) if v is not None else None)
    return df


async def _download_one(client, dataset_id: str) -> dict:
    meta = await _with_retry(f"{dataset_id} meta", client.get_dataset, dataset_id)
    metas = (meta.model_dump().get("metas") or {}).get("default") or {}
    raw = await _with_retry(f"{dataset_id} export", client.export_data, dataset_id, format="json")
    df = _flatten(pd.DataFrame(json.load(io.BytesIO(raw))))
    df.to_parquet(RAW_DIR / f"{dataset_id}.parquet", index=False)
    print(f"  {dataset_id}: {len(df):,} rows")
    return {
        "dataset_id": dataset_id,
        "title": metas.get("title"),
        "license": metas.get("license"),
        "modified": str(metas.get("modified")),
        "data_processed": str(metas.get("data_processed")),
        "rows": len(df),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def download_datasets(ids: list[str]) -> None:
    from dotenv import load_dotenv
    from ukpyn import UKPNClient

    load_dotenv()
    if not os.getenv("UKPN_API_KEY"):
        raise SystemExit("UKPN_API_KEY is not set. Set it in the environment (or a local .env).")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW_DIR / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    async with UKPNClient(timeout=300) as client:
        for dataset_id in ids:
            print(f"Downloading {dataset_id} ...")
            manifest[dataset_id] = await _download_one(client, dataset_id)
            manifest_path.write_text(json.dumps(manifest, indent=2))


# ----------------------------------------------------------------- helpers --


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip().lower()


def _gsp_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.upper().replace("KV", "")).strip()


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


class UKPNAdapter(DNOAdapter):
    dno = "UKPN"
    default_scenario = DEFAULT_SCENARIO

    def __init__(self, raw_dir: Path = RAW_DIR):
        self.raw_dir = raw_dir

    def download(self, refresh: bool = False) -> None:
        missing = [d for d in DATASETS if refresh or not (self.raw_dir / f"{d}.parquet").exists()]
        if missing:
            asyncio.run(download_datasets(missing))

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
            }
        ).drop_duplicates("gsp")

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
        }
