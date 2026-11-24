"""Data quality checks (Phase 11). Run on every build; a failure stops the deploy.

Usage:  uv run python -m pipeline.checks     (exit code 1 if any check fails)

Thresholds are set just below today's values (docs/PROFILE.md), so a format
change or a broken join at UKPN shows up as a failed check instead of quietly
wrong numbers. DNO-agnostic: works on the normalised tables and bronze manifests.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from . import bronze

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "grid.duckdb"
UK_BOX = {"lat": (49.5, 56.5), "lon": (-6.5, 2.5)}  # covers every DNO in Great Britain's south and east
ROW_CHANGE_LIMIT = 0.20  # a dataset may grow or shrink by up to 20% between snapshots


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _share(n: int, d: int) -> float:
    return n / d if d else 0.0


def check_tables(t: dict[str, pd.DataFrame]) -> list[Check]:
    s, b, fs, sc = t["sites"], t["bsps"], t["field_sources"], t["site_scores"]
    out: list[Check] = []
    add = lambda name, ok, detail: out.append(Check(name, bool(ok), detail))  # noqa: E731

    add("sites present", len(s) >= 900, f"{len(s)} sites (expect ≥ 900)")
    add("site IDs unique", not s["site_id"].duplicated().any(), "no duplicate site_id")
    floc = _share((~s["site_id"].str.startswith("UKPN-MRID-")).sum(), len(s))
    add("sites matched to a FLOC", floc >= 0.99, f"{floc:.1%} (expect ≥ 99%)")
    in_box = s["lat"].between(*UK_BOX["lat"]) & s["lon"].between(*UK_BOX["lon"])
    add("locations present and in Great Britain", _share(in_box.sum(), len(s)) >= 0.99, f"{_share(in_box.sum(), len(s)):.1%} (expect ≥ 99%)")
    scorable = s["scorable"].sum()
    add("scorable sites", _share(scorable, len(s)) >= 0.98, f"{scorable} of {len(s)} (expect ≥ 98%)")
    add("GSP mapped", _share(s["gsp_mapped"].sum(), len(s)) >= 0.98, f"{_share(s['gsp_mapped'].sum(), len(s)):.1%} (expect ≥ 98%)")
    head = s.loc[s["scorable"], "demand_headroom_mw"]
    add("published headroom filled", _share(head.notna().sum(), len(head)) >= 0.99, f"{_share(head.notna().sum(), len(head)):.1%} of scorable sites")
    q = s.loc[s["scorable"], "queue_mw"]
    add("queue filled and non-negative", q.notna().all() and (q >= 0).all(), "queue_mw present and ≥ 0 for every scorable site")

    matched = _share(b["matched"].sum(), len(b))
    add("BSPs matched to published headroom", matched >= 0.90, f"{b['matched'].sum()} of {len(b)} = {matched:.1%} (expect ≥ 90%)")
    sc_sites = s[s["scorable"]]
    path = sc_sites["bsp_id"].isna() | sc_sites["bsp_headroom_mw"].notna()
    add("scorable sites with a known upstream path", _share(path.sum(), len(sc_sites)) >= 0.95,
        f"{_share(path.sum(), len(sc_sites)):.1%} (direct-fed or BSP headroom published; expect ≥ 95%)")

    scores = sc["score"].dropna()
    add("scores in 0–100", scores.between(0, 100).all() and len(scores) >= 0.98 * len(sc),
        f"{len(scores)} scores, min {scores.min():.1f}, max {scores.max():.1f}")
    add("rank 1 exists", (sc["rank"] == 1).any(), "a top-ranked site exists")

    dates_ok = fs["publish_date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")
    future = pd.to_datetime(fs["publish_date"], errors="coerce") > pd.Timestamp(date.today())
    add("every field has a dataset, publish date and licence",
        fs["dataset_id"].notna().all() and dates_ok.all() and fs["licence"].fillna("").ne("").all() and not future.any(),
        f"{len(fs)} field sources checked")
    return out


def check_bronze(dno: str = "UKPN", root: Path = bronze.BRONZE_ROOT) -> list[Check]:
    """Each dataset's row count vs the previous snapshot."""
    snaps = bronze.snapshots(dno, root)
    if len(snaps) < 2:
        return [Check("row counts vs previous snapshot", True, "only one snapshot: nothing to compare")]
    prev = json.loads((snaps[-2] / "_manifest.json").read_text())
    last = json.loads((snaps[-1] / "_manifest.json").read_text())
    out = []
    for ds, m in last.items():
        if ds not in prev or not prev[ds].get("rows"):
            continue
        change = (m["rows"] - prev[ds]["rows"]) / prev[ds]["rows"]
        out.append(Check(f"rows: {ds}", abs(change) <= ROW_CHANGE_LIMIT,
                         f"{prev[ds]['rows']:,} → {m['rows']:,} ({change:+.0%}, limit ±{ROW_CHANGE_LIMIT:.0%})"))
    missing = sorted(set(prev) - set(last))
    out.append(Check("no dataset missing from the latest snapshot", not missing, f"missing: {missing}" if missing else "all present"))
    return out


def run(db_path: Path = DB_PATH) -> list[Check]:
    with duckdb.connect(str(db_path), read_only=True) as con:
        t = {n: con.execute(f"SELECT * FROM {n}").df() for n in ("sites", "bsps", "field_sources", "site_scores")}
        snaps = con.execute("SELECT snapshot_date, count(*) n FROM silver.sites GROUP BY 1 ORDER BY 1").df()
    checks = check_tables(t) + check_bronze()
    latest_rows = int(snaps["n"].iloc[-1]) if len(snaps) else 0
    checks.append(Check("silver latest snapshot matches the current tables", latest_rows == len(t["sites"]),
                        f"silver {latest_rows} rows vs sites {len(t['sites'])}"))
    return checks


def report(checks: list[Check]) -> bool:
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"  {'PASS' if c.ok else 'FAIL'}  {c.name:<{width}}  {c.detail}")
    failed = [c for c in checks if not c.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return not failed


def main() -> None:
    sys.exit(0 if report(run()) else 1)


if __name__ == "__main__":
    main()
