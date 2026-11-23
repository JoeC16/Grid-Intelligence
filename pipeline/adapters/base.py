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


class DNOAdapter(ABC):
    """One per DNO. Implementations live in pipeline/adapters/<dno>.py."""

    #: Short code, e.g. "UKPN".
    dno: str
    #: DFES scenario used for the headline headroom_2030_mw.
    default_scenario: str

    def download(self, refresh: bool = False) -> None:  # noqa: B027 - optional hook
        """Fetch raw data to local storage. No-op if the adapter reads live."""

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
        """GSP list with location: gsp, licence_area, lat, lon (one row per gsp)."""

    @abstractmethod
    def sources(self) -> dict[str, Source]:
        """Map each output field (e.g. 'queue_mw') to its Source."""
