"""DNO adapter interface.

Every DNO plugs into the pipeline through a DNOAdapter. Adapters own everything
DNO-specific (dataset IDs, column names, name matching, quirks) and return
plain DataFrames in the shapes documented below. normalise.py only ever sees
these shapes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

# Column contracts for each fetch_* method. normalise.py checks these.
SITES_COLUMNS = [
    "site_id",        # stable ID, unique per substation (UKPN: FLOC)
    "name",
    "lat",
    "lon",
    "voltage_kv",     # busbar voltage the headroom refers to, e.g. 11.0
    "licence_area",   # e.g. "LPN"
    "gsp",            # GSP name as used in the DNO's GSP list; None if unmapped
    "gsp_mapped",     # bool
    "exclude_reason",  # None, or why the site must not be scored
]
HEADROOM_COLUMNS = [
    "site_id",
    "firm_capacity_mw",
    "observed_peak_mw",
    "demand_headroom_mw",  # published (firm) demand headroom
]
FUTURE_HEADROOM_COLUMNS = ["site_id", "scenario", "year", "headroom_mw"]
QUEUE_COLUMNS = [
    "site_id",
    "queue_mw",               # demand MW offered and not yet connected
    "queue_source",           # dataset ID the figure came from, or "none"
    "connections_last_year",  # count of demand offers accepted in the past year
]
GSP_QUEUE_COLUMNS = [
    "gsp",       # GSP name, or "(unmapped)"
    "queue_mw",  # demand queued at grid level, i.e. not under any site in fetch_sites
]
# Network topology (Phase 8). One row per bulk supply point (BSP).
BSP_COLUMNS = [
    "bsp_id",          # stable ID
    "name",
    "licence_area",
    "lat",
    "lon",
    "site_id",         # the map site that is this BSP's own board, if any
    "gsp",             # GSP name as in fetch_gsps(); None if unknown
    "headroom_mw",     # published demand headroom at the BSP; None if not published
    "headroom_source", # dataset ID the headroom came from
    "matched",         # bool: the BSP was matched to a substation with published headroom
    "note",            # why not matched, if not
]
# Which BSP each site hangs off. bsp_id None = fed directly from its GSP.
BSP_LINK_COLUMNS = ["site_id", "bsp_id"]
LARGE_DEMAND_COLUMNS = [
    "project_id",
    "licence_area",
    "gsp",
    "technology",     # "large_demand" (demand-only, >=5 MVA) or "der" (e.g. battery)
    "import_capacity_mva",
    "application_date",
]


@dataclass(frozen=True)
class Source:
    """Where a field's numbers come from, for links in the UI."""

    dataset_id: str
    publish_date: str  # YYYY-MM-DD
    url: str
    licence: str = ""  # e.g. "CC BY 4.0", as published with the dataset


@dataclass(frozen=True)
class DNOInfo:
    """How a DNO is named, attributed and checked. The app reads every DNO-specific
    word from this (via the `dnos` table), so nothing outside adapters/ names a DNO."""

    code: str                 # e.g. "UKPN"; matches sites.dno
    name: str                 # e.g. "UK Power Networks"
    region: str               # plain-English area, e.g. "London, the South East and the East of England"
    licence_areas: tuple[str, ...]
    portal_name: str          # e.g. "UK Power Networks Open Data Portal"
    portal_url: str
    licence: str              # licence of the open data, e.g. "CC BY 4.0"
    licence_url: str
    map_center: tuple[float, float]  # lon, lat for "show the whole network"
    map_zoom: float
    min_sites: int            # data quality check: fewer sites than this = a broken download
    fallback_id_prefix: str   # site_id prefix used when a site can't be matched to its stable ID

    def as_row(self) -> dict:
        d = self.__dict__.copy()
        d["licence_areas"] = ",".join(self.licence_areas)
        d["map_lon"], d["map_lat"] = d.pop("map_center")
        return d


class DNOAdapter(ABC):
    """One per DNO. Implementations live in pipeline/adapters/<dno>.py."""

    #: Short code, e.g. "UKPN".
    dno: str
    #: Names, attribution, map view and check thresholds.
    info: DNOInfo
    #: DFES scenario used for the headline headroom_2030_mw.
    default_scenario: str

    def download(self, refresh: bool = False) -> None:  # noqa: B027 - optional hook
        """Fetch raw data to local storage. No-op if the adapter reads live."""

    # Bronze snapshots (Phase 10). Adapters without snapshots have exactly one.
    @property
    def snapshot_date(self) -> str:
        return "current"

    def snapshot_dates(self) -> list[str]:
        return [self.snapshot_date]

    def for_snapshot(self, snapshot_date: str) -> "DNOAdapter":
        """An adapter reading the given snapshot."""
        return self

    @abstractmethod
    def fetch_sites(self) -> pd.DataFrame:
        """One row per scorable substation. Columns: SITES_COLUMNS."""

    @abstractmethod
    def fetch_headroom(self) -> pd.DataFrame:
        """Current capacity and headroom per site. Columns: HEADROOM_COLUMNS."""

    @abstractmethod
    def fetch_future_headroom(self) -> pd.DataFrame:
        """Long table of forecast headroom. Columns: FUTURE_HEADROOM_COLUMNS."""

    @abstractmethod
    def fetch_queue(self) -> pd.DataFrame:
        """Demand queue and recent activity per site. Columns: QUEUE_COLUMNS."""

    @abstractmethod
    def fetch_gsp_queue(self) -> pd.DataFrame:
        """Queue that can't be attributed to a site (e.g. 132kV). Columns: GSP_QUEUE_COLUMNS."""

    @abstractmethod
    def fetch_large_demand(self) -> pd.DataFrame:
        """Large committed demand projects (GSP level). Columns: LARGE_DEMAND_COLUMNS."""

    @abstractmethod
    def fetch_gsps(self) -> pd.DataFrame:
        """GSP list: gsp, licence_area, lat, lon, import_capacity_utilisation_pct,
        technical_limit_rag ("GREEN" = technical limits agreed with the system operator,
        "RED" = not yet; not a constraint signal). One row per gsp."""

    @abstractmethod
    def fetch_topology(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(BSPs with BSP_COLUMNS, site→BSP links with BSP_LINK_COLUMNS)."""

    @abstractmethod
    def sources(self) -> dict[str, Source]:
        """Map each output field (e.g. 'queue_mw') to its Source."""
