"""Spain: demand access capacity for every distribution network, from the CNMC maps (Phase 13).

Source: the CNMC's national demand capacity map (Mapas de capacidad de acceso,
published monthly since April 2026). It merges what every distribution network
operator must report under Circular informativa 6/2025: for each substation
busbar above 1 kV, the firm demand access capacity still available, the
capacity already taken (ocupada) and the capacity of requests admitted but
not yet evaluated. The map's data sits in public ArcGIS feature services; no
key is needed.

How it maps onto the common schema:
  site                one busbar (substation × voltage), as published
  demand_headroom_mw  Capacidad de acceso firme disponible (MW)  → "published headroom"
  queue_mw            Capacidad admitida y no evaluada (MW)
  capacity_taken_mw   Capacidad ocupada (MW): utilisation = taken / (taken + available)
  licence_area        the distributor (the five large ones by name, the rest "Small distributors")
Not published for Spain, so left missing: firm capacity and peak demand,
connections in the past year, forecast headroom, the GSP/BSP tree, large demand.

Busbars the operator flags "Nudo 0" are shown but not scored: the CNMC data
doesn't define the flag, and every flagged busbar shows zero available capacity,
so scoring it as "full" could be wrong.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

import pandas as pd

from .. import bronze
from . import ods
from .base import DNOAdapter, DNOInfo, Source

DNO = "ES"
SERVICES = "https://services9.arcgis.com/F9FmuOlj5xjEjPRZ/arcgis/rest/services"
MAP_PAGE = "https://www.cnmc.es/sectores-que-regulamos/energia/supervision-del-mercado-electrico/informe-acceso-y-conexion-redes"
LICENCE = "CC BY-SA 4.0"  # CNMC open data terms (data.cnmc.es/condiciones-de-uso)

# dataset_id -> (feature layer, title)
DIST_DS = "cnmc-demanda-en-distribucion"
TRANS_DS = "cnmc-demanda-en-transporte"
PERIOD_DS = "cnmc-capacidad-periodo"
LAYERS = {
    DIST_DS: ("Demanda_en_Distribucion/FeatureServer/4", "CNMC: capacidad de acceso de demanda en redes de distribución"),
    TRANS_DS: ("Demanda_en_Transporte_v2/FeatureServer/11", "CNMC: capacidad de acceso de demanda en la red de transporte"),
    PERIOD_DS: ("Capacidad_Periodo/FeatureServer/10", "CNMC: periodo de los mapas de capacidad"),
}

# The five large distributors get their own filter chip; everyone else is grouped.
LARGE_DISTRIBUTORS = {
    "R1-001": "i-DE",
    "R1-299": "e-distribución",
    "R1-002": "UFD",
    "R1-008": "Hidrocantábrico",
    "R1-005": "Viesgo",
}
SMALL = "Small distributors"

# Mainland, Balearics, Canaries, Ceuta and Melilla.
SPAIN_BOXES = [((35.0, 44.0), (-9.6, 4.5)), ((27.4, 29.5), (-18.3, -13.3))]

INFO = DNOInfo(
    code=DNO,
    name="Spain's distribution networks",
    region="Spain: every distribution network operator reporting to the CNMC",
    licence_areas=(*LARGE_DISTRIBUTORS.values(), SMALL),
    portal_name="CNMC capacity maps (Mapas de capacidad de acceso)",
    portal_url=MAP_PAGE,
    licence=LICENCE,
    licence_url="https://creativecommons.org/licenses/by-sa/4.0/",
    map_center=(-3.6, 40.2),
    map_zoom=5.3,
    min_sites=5000,
    fallback_id_prefix="ES-UNMATCHED-",  # never used: every busbar has an operator, substation and voltage
    country="ES",
    publisher="CNMC",
    has_topology=False,
    bbox=((27.4, 44.0), (-18.3, 4.5)),
    min_scorable_share=0.90,  # "Nudo 0" busbars (6.6% in Oct 2026) are shown but not scored
)


# ---------------------------------------------------------------- download --


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r)


def _query_all(layer: str) -> pd.DataFrame:
    """Every feature of a layer, in WGS84, paging past the 2,000-row limit."""
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": "*", "outSR": 4326, "resultOffset": offset,
                                    "resultRecordCount": 2000, "orderByFields": "OBJECTID", "f": "json"})
        d = _get_json(f"{SERVICES}/{layer}/query?{q}")
        if "error" in d:
            raise RuntimeError(f"{layer}: {d['error']}")
        feats = d.get("features", [])
        for f in feats:
            g = f.get("geometry") or {}
            rows.append(f["attributes"] | {"lon": g.get("x"), "lat": g.get("y")})
        if not d.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return pd.DataFrame(rows)


async def _download(ids: list[str], out_dir: Path) -> None:
    import asyncio

    manifest = ods.Manifest(out_dir)
    period = None
    for ds in [PERIOD_DS, *[i for i in ids if i != PERIOD_DS]]:
        layer, title = LAYERS[ds]
        print(f"Downloading {ds} ...")
        info = await ods.with_retry(f"{ds} meta", asyncio.to_thread, _get_json, f"{SERVICES}/{layer}?f=json")
        df = await ods.with_retry(f"{ds} query", asyncio.to_thread, _query_all, layer)
        if ds == PERIOD_DS and len(df):
            period = f"{int(df['ANIO'].iloc[0])}-{str(df['PERIODO'].iloc[0])[:2]}"  # PERIODO "102026" -> 2026-10
        edited = (info.get("editingInfo") or {}).get("lastEditDate")
        modified = datetime.fromtimestamp(edited / 1000, timezone.utc).date().isoformat() if edited else None
        entry = ods.save(df, ds, {"title": title, "license": LICENCE, "modified": modified}, out_dir)
        entry["period"] = period
        entry["url"] = f"{SERVICES}/{layer}"
        manifest.add(entry)


# ----------------------------------------------------------------- adapter --


def _slug(s: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "-", str(s).upper()).strip("-")


def _in_spain(lat: pd.Series, lon: pd.Series) -> pd.Series:
    ok = pd.Series(False, index=lat.index)
    for (la, lo) in SPAIN_BOXES:
        ok |= lat.between(*la) & lon.between(*lo)
    return ok


class CNMCSpainAdapter(DNOAdapter):
    dno = DNO
    info = INFO
    default_scenario = "none"  # Spain publishes no DFES-style forecast

    def __init__(self, raw_dir: Path | None = None):
        self.raw_dir = raw_dir or bronze.latest(DNO) or bronze.snapshot_dir(DNO)

    @property
    def snapshot_date(self) -> str:
        return self.raw_dir.name

    def snapshot_dates(self) -> list[str]:
        return [p.name for p in bronze.snapshots(DNO)]

    def for_snapshot(self, snapshot_date: str) -> "CNMCSpainAdapter":
        return CNMCSpainAdapter(bronze.BRONZE_ROOT / DNO.lower() / snapshot_date)

    def download(self, refresh: bool = False) -> None:
        import asyncio

        if refresh:
            self.raw_dir = bronze.snapshot_dir(DNO)
            missing = list(LAYERS)
        else:
            missing = [d for d in LAYERS if not (self.raw_dir / f"{d}.parquet").exists()]
        if missing:
            asyncio.run(_download(missing, self.raw_dir))
            type(self)._busbars.cache_clear()
            type(self)._manifest.cache_clear()

    @cache
    def _manifest(self) -> dict:
        return json.loads((self.raw_dir / "_manifest.json").read_text())

    @cache
    def _busbars(self) -> pd.DataFrame:
        """One row per published busbar, with a stable site_id."""
        d = pd.read_parquet(self.raw_dir / f"{DIST_DS}.parquet")
        d["SUBESTACION"] = d["SUBESTACION"].fillna("").str.strip()
        base = "ES-" + d["GESTOR_RED"] + "-" + d["SUBESTACION"].map(_slug) + "-" + d["NIVEL_TENSION"].astype(str) + "KV"
        # A few substations publish two busbars at the same voltage: number them in a fixed order.
        d = d.assign(_base=base).sort_values(["_base", "COORDENADA_UTM_X", "COORDENADA_UTM_Y", "OBJECTID"])
        n = d.groupby("_base").cumcount() + 1
        many = d["_base"].map(d["_base"].value_counts()) > 1
        d["site_id"] = d["_base"].where(~many, d["_base"] + "-B" + n.astype(str))
        kv = d["NIVEL_TENSION"].map(lambda v: f"{v:g}")
        d["name"] = (d["SUBESTACION"] + " " + kv + " kV").where(~many, d["SUBESTACION"] + " " + kv + " kV (busbar " + n.astype(str) + ")")
        return d.reset_index(drop=True)

    def fetch_sites(self) -> pd.DataFrame:
        d = self._busbars()
        located = _in_spain(d["lat"], d["lon"])
        reason = pd.Series(None, index=d.index, dtype=object)
        reason[d["NUDO_0"].fillna(0).astype(int) == 1] = (
            "Flagged 'Nudo 0' by its operator. The CNMC data doesn't define this flag, so it isn't scored.")
        reason[~located] = "Published location is outside Spain."
        return pd.DataFrame({
            "site_id": d["site_id"], "name": d["name"], "lat": d["lat"], "lon": d["lon"],
            "voltage_kv": d["NIVEL_TENSION"].astype(float),
            "licence_area": d["GESTOR_RED"].map(LARGE_DISTRIBUTORS).fillna(SMALL),
            "gsp": None, "gsp_mapped": False, "exclude_reason": reason,
            # optional Spain extras (normalise.OPTIONAL_SITE_COLUMNS)
            "operator": d["GESTOR_RED"], "operator_name": d["DESCRIPCION"].str.strip(),
            "province": d["PROVINCIA"], "municipality": d["MUNICIPIO"],
            "reserved": d["CAP_COMPROMETIDA"].fillna(0).astype(int) == 1,
        })

    def fetch_headroom(self) -> pd.DataFrame:
        d = self._busbars()
        return pd.DataFrame({
            "site_id": d["site_id"], "firm_capacity_mw": float("nan"), "observed_peak_mw": float("nan"),
            "demand_headroom_mw": d["CAP_DISPONIBLE"].astype(float),
            "capacity_taken_mw": d["CAP_OCUPADA"].astype(float),
        })

    def fetch_future_headroom(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["site_id", "scenario", "year", "headroom_mw"])

    def fetch_queue(self) -> pd.DataFrame:
        d = self._busbars()
        return pd.DataFrame({
            "site_id": d["site_id"], "queue_mw": d["CAP_ADMITIDA_NO_EVALUADA"].astype(float).fillna(0.0),
            "queue_source": DIST_DS, "connections_last_year": float("nan"),
        })

    def fetch_gsp_queue(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["gsp", "queue_mw"])

    def fetch_large_demand(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["project_id", "licence_area", "gsp", "technology", "import_capacity_mva",
                                     "application_date"])

    def fetch_gsps(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["gsp", "licence_area", "lat", "lon", "import_capacity_utilisation_pct",
                                     "technical_limit_rag"])

    def fetch_topology(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        from .base import BSP_COLUMNS, BSP_LINK_COLUMNS

        return pd.DataFrame(columns=BSP_COLUMNS), pd.DataFrame(columns=BSP_LINK_COLUMNS)

    def period(self) -> str | None:
        """The month the CNMC figures describe, e.g. '2026-10'."""
        return self._manifest().get(DIST_DS, {}).get("period")

    def sources(self) -> dict[str, Source]:
        m = self._manifest()[DIST_DS]
        src = Source(DIST_DS, m.get("modified") or self.snapshot_date, MAP_PAGE, m.get("license") or LICENCE)
        return {f: src for f in ("name", "lat", "lon", "voltage", "licence_area", "demand_headroom_mw",
                                 "queue_mw", "capacity_taken_mw", "operator")}
