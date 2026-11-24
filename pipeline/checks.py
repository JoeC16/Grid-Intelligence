"""Data quality checks (Phase 11). Run on every build; a failure stops the deploy.

Usage:  uv run python -m pipeline.checks     (exit code 1 if any check fails)

Thresholds are set just below today's values (docs/PROFILE.md), so a format
change or a broken join at a DNO shows up as a failed check instead of quietly
wrong numbers. DNO-agnostic: site checks run once per DNO in the `dnos` table, using
its own thresholds (DNOInfo in pipeline/adapters/), plus national checks.
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


def check_dno(dno: dict, s: pd.DataFrame, b: pd.DataFrame, fs: pd.DataFrame) -> list[Check]:
    """Checks on one DNO's rows. `dno` is its row of the dnos table."""
    out: list[Check] = []
    tag = dno["code"]
    add = lambda name, ok, detail: out.append(Check(f"{tag}: {name}", bool(ok), detail))  # noqa: E731

    add("sites present", len(s) >= dno["min_sites"], f"{len(s)} sites (expect ≥ {dno['min_sites']})")
    matched_id = _share((~s["site_id"].str.startswith(dno["fallback_id_prefix"])).sum(), len(s))
    add("sites matched to a stable ID", matched_id >= 0.99, f"{matched_id:.1%} (expect ≥ 99%)")
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

    dates_ok = fs["publish_date"].astype(str).str.match(r"^\d{4}-\d{2}-\d{2}$")
    future = pd.to_datetime(fs["publish_date"], errors="coerce") > pd.Timestamp(date.today())
    add("every field has a dataset, publish date and licence",
        len(fs) > 0 and fs["dataset_id"].notna().all() and dates_ok.all()
        and fs["licence"].fillna("").ne("").all() and not future.any(),
        f"{len(fs)} field sources checked")
    return out


def check_tables(t: dict[str, pd.DataFrame]) -> list[Check]:
    """Per-DNO checks for every DNO in the dnos table, then national ones."""
    s, b, fs, sc, g = t["sites"], t["bsps"], t["field_sources"], t["site_scores"], t["gsps"]
    out: list[Check] = []
    for dno in t["dnos"].to_dict("records"):
        code = dno["code"]
        out += check_dno(dno, s[s["dno"] == code], b[b["dno"] == code], fs[fs["dno"] == code])
    unknown = sorted(set(s["dno"]) - set(t["dnos"]["code"]))
    add = lambda name, ok, detail: out.append(Check(name, bool(ok), detail))  # noqa: E731
    add("every site's DNO is described", not unknown, f"unknown: {unknown}" if unknown else f"{len(t['dnos'])} DNO(s)")
    add("site IDs unique", not s["site_id"].duplicated().any(), "no duplicate site_id across DNOs")
    add("GSP names unique", not g["gsp"].duplicated().any(), "no GSP name used by two DNOs")

    scores = sc["score"].dropna()
    add("scores in 0–100", scores.between(0, 100).all() and len(scores) >= 0.98 * len(sc),
        f"{len(scores)} scores, min {scores.min():.1f}, max {scores.max():.1f}")
    add("rank 1 exists", (sc["rank"] == 1).any(), "a top-ranked site exists")
    return out


def check_bronze(dno: str, root: Path = bronze.BRONZE_ROOT) -> list[Check]:
    """Each dataset's row count vs the previous snapshot."""
    snaps = bronze.snapshots(dno, root)
    if len(snaps) < 2:
        return [Check(f"{dno}: row counts vs previous snapshot", True, "only one snapshot: nothing to compare")]
    prev = json.loads((snaps[-2] / "_manifest.json").read_text())
    last = json.loads((snaps[-1] / "_manifest.json").read_text())
    out = []
    for ds, m in last.items():
        if ds not in prev or not prev[ds].get("rows"):
            continue
        change = (m["rows"] - prev[ds]["rows"]) / prev[ds]["rows"]
        out.append(Check(f"{dno}: rows: {ds}", abs(change) <= ROW_CHANGE_LIMIT,
                         f"{prev[ds]['rows']:,} → {m['rows']:,} ({change:+.0%}, limit ±{ROW_CHANGE_LIMIT:.0%})"))
    missing = sorted(set(prev) - set(last))
    out.append(Check(f"{dno}: no dataset missing from the latest snapshot", not missing, f"missing: {missing}" if missing else "all present"))
    return out


def run(db_path: Path = DB_PATH) -> list[Check]:
    with duckdb.connect(str(db_path), read_only=True) as con:
        t = {n: con.execute(f"SELECT * FROM {n}").df()
             for n in ("sites", "bsps", "gsps", "field_sources", "site_scores", "dnos")}
        # Each DNO's latest silver snapshot (DNOs can be on different snapshot dates).
        latest = con.execute("""
            SELECT dno, count(*) n FROM silver.sites
            WHERE (dno, snapshot_date) IN (SELECT dno, max(snapshot_date) FROM silver.sites GROUP BY 1)
            GROUP BY 1""").df().set_index("dno")["n"]
    checks = check_tables(t)
    for code in t["dnos"]["code"]:
        checks += check_bronze(code)
    current = t["sites"]["dno"].value_counts()
    ok = all(int(latest.get(d, 0)) == int(n) for d, n in current.items())
    checks.append(Check("silver latest snapshot matches the current tables", ok,
                        ", ".join(f"{d}: silver {int(latest.get(d, 0))} vs sites {int(n)}" for d, n in current.items())))
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
