"""Phase 1 data spike: download raw UKPN datasets to data/raw/ as parquet.

Usage:  uv run python -m pipeline.download_raw [dataset_id ...]

Reads UKPN_API_KEY from the environment (python-dotenv .env as local fallback).
The key is never printed or written anywhere.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from ukpyn import UKPNClient

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"

# Dataset IDs on the UKPN Open Data Portal. All cover LPN, SPN and EPN.
DATASETS = [
    "ukpn-grid-supply-points-overview",       # GSP-level demand/generation queue
    "ukpn-dfes-network-headroom-report",      # DFES headroom by substation/year/scenario
    "ukpn-ltds-table-3a-load-data-observed",  # LTDS observed peak demand + firm capacity
    "grid-and-primary-sites",                 # grid & primary substation locations
    "ukpn-capacity-heatmap",                  # LTDS capacity heatmap (demand headroom)
]

RETRIES = 6


async def with_retry(label: str, fn, *args, **kwargs):
    """The egress path to the portal drops connections intermittently."""
    for attempt in range(1, RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry anything
            if attempt == RETRIES:
                raise
            wait = 2 ** attempt
            print(f"  {label}: {type(exc).__name__}, retry {attempt}/{RETRIES - 1} in {wait}s")
            await asyncio.sleep(wait)


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Turn nested dict columns (e.g. geo points) into flat columns parquet can store."""
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


async def download(client: UKPNClient, dataset_id: str) -> dict:
    meta = await with_retry(f"{dataset_id} meta", client.get_dataset, dataset_id)
    metas = (meta.model_dump().get("metas") or {}).get("default") or {}
    raw = await with_retry(f"{dataset_id} export", client.export_data, dataset_id, format="json")
    df = flatten(pd.DataFrame(json.load(io.BytesIO(raw))))
    out = RAW_DIR / f"{dataset_id}.parquet"
    df.to_parquet(out, index=False)
    print(f"  {dataset_id}: {len(df):,} rows, {len(df.columns)} cols -> {out.name}")
    return {
        "dataset_id": dataset_id,
        "title": metas.get("title"),
        "license": metas.get("license"),
        "modified": str(metas.get("modified")),
        "data_processed": str(metas.get("data_processed")),
        "rows": len(df),
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


async def main(ids: list[str]) -> None:
    load_dotenv()
    if not os.getenv("UKPN_API_KEY"):
        sys.exit("UKPN_API_KEY is not set. Set it in the environment (or a local .env).")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW_DIR / "_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    async with UKPNClient(timeout=300) as client:
        for dataset_id in ids:
            print(f"Downloading {dataset_id} ...")
            manifest[dataset_id] = await download(client, dataset_id)
            manifest_path.write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or DATASETS))
