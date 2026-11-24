"""Print "true" if any dataset differs between two bronze snapshots, else "false".

Usage:  uv run python -m pipeline.snapshot_diff <previous_dir> <latest_dir>

Compares each dataset's portal publish date and row count from the manifests.
Used by the refresh workflow to store a snapshot only when a DNO (or the CNMC) republished something.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def changed(prev: Path, last: Path) -> bool:
    a = json.loads((prev / "_manifest.json").read_text())
    b = json.loads((last / "_manifest.json").read_text())
    if set(a) != set(b):
        return True
    return any((a[k].get("modified"), a[k].get("rows")) != (b[k].get("modified"), b[k].get("rows")) for k in a)


if __name__ == "__main__":
    print("true" if changed(Path(sys.argv[1]), Path(sys.argv[2])) else "false")
