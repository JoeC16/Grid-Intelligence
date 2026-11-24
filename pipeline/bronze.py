"""Bronze layer: raw downloads exactly as received, one folder per snapshot.

    data/bronze/<dno>/<YYYY-MM-DD>/<dataset>.parquet + _manifest.json

A refresh writes a new snapshot folder; nothing is overwritten (a second
refresh on the same day replaces that day's files). DNO-agnostic.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

BRONZE_ROOT = Path(__file__).resolve().parent.parent / "data" / "bronze"
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def snapshots(dno: str, root: Path = BRONZE_ROOT) -> list[Path]:
    """Snapshot folders for a DNO, oldest first."""
    base = root / dno.lower()
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and _DATE.match(p.name))


def latest(dno: str, root: Path = BRONZE_ROOT) -> Path | None:
    snaps = snapshots(dno, root)
    return snaps[-1] if snaps else None


def snapshot_dir(dno: str, day: date | None = None, root: Path = BRONZE_ROOT) -> Path:
    """Folder for a snapshot taken on `day` (default today). Not created."""
    return root / dno.lower() / (day or date.today()).isoformat()
