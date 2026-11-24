"""Shared download helpers for DNO open data portals on OpenDataSoft.

UKPN, SP Energy Networks and several other DNOs publish on OpenDataSoft
(<org>.opendatasoft.com), with the same Explore API v2.1. This module:
- exports whole datasets with retries (the network path to these hosts drops connections),
- flattens nested fields so parquet can store them,
- writes each bronze snapshot's _manifest.json (title, licence, publish date, rows).

UKPN keeps using ukpyn for the transport (project rule); other DNOs use
`download_datasets` here with plain HTTP. API keys come only from the environment.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable

import pandas as pd

RETRIES = 6


async def with_retry(label: str, fn: Callable[..., Awaitable], *args, **kwargs):
    """Call fn, retrying with exponential backoff on any error."""
    for attempt in range(1, RETRIES + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - network flakiness, retry anything
            if attempt == RETRIES:
                raise
            wait = 2**attempt
            print(f"  {label}: {type(exc).__name__}, retry {attempt}/{RETRIES - 1} in {wait}s")
            await asyncio.sleep(wait)


def flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Turn nested dict/list columns into flat columns parquet can store.
    Geo points {lat, lon} also get <col>_lat and <col>_lon columns."""
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


def manifest_entry(dataset_id: str, metas: dict, rows: int) -> dict:
    """One dataset's line in _manifest.json. `metas` is the portal's metas.default."""
    return {
        "dataset_id": dataset_id,
        "title": metas.get("title"),
        "license": metas.get("license"),
        "modified": str(metas.get("modified")),
        "data_processed": str(metas.get("data_processed")),
        "rows": rows,
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def save(df: pd.DataFrame, dataset_id: str, metas: dict, out_dir: Path) -> dict:
    """Write one dataset to bronze and return its manifest entry."""
    df = flatten(df)
    df.to_parquet(out_dir / f"{dataset_id}.parquet", index=False)
    print(f"  {dataset_id}: {len(df):,} rows")
    return manifest_entry(dataset_id, metas, len(df))


class Manifest:
    """_manifest.json for one snapshot folder, written after every dataset so a
    dropped connection mid-run keeps what was already downloaded."""

    def __init__(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        self.path = out_dir / "_manifest.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def add(self, entry: dict) -> None:
        self.data[entry["dataset_id"]] = entry
        self.path.write_text(json.dumps(self.data, indent=2))


def api_key(env_var: str) -> str:
    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv(env_var)
    if not key:
        raise SystemExit(f"{env_var} is not set. Set it in the environment (or a local .env).")
    return key


async def download_datasets(base_url: str, ids: list[str], out_dir: Path, key_env: str) -> None:
    """Export each dataset from an OpenDataSoft portal into out_dir (one bronze snapshot).

    base_url: e.g. "https://spenergynetworks.opendatasoft.com". The key is sent as
    `Authorization: Apikey <key>`, as OpenDataSoft expects.
    """
    import httpx

    key = api_key(key_env)
    manifest = Manifest(out_dir)
    api = f"{base_url.rstrip('/')}/api/explore/v2.1/catalog/datasets"
    headers = {"Authorization": f"Apikey {key}"}

    async def get(client: httpx.AsyncClient, url: str) -> httpx.Response:
        r = await client.get(url)
        r.raise_for_status()
        return r

    async with httpx.AsyncClient(headers=headers, timeout=300, follow_redirects=True) as client:
        for ds in ids:
            print(f"Downloading {ds} ...")
            meta = (await with_retry(f"{ds} meta", get, client, f"{api}/{ds}")).json()
            raw = (await with_retry(f"{ds} export", get, client, f"{api}/{ds}/exports/json")).content
            rows = json.load(io.BytesIO(raw))
            if not rows:
                # Anonymous or under-privileged keys get an empty export, not an error.
                raise SystemExit(f"{ds}: the portal returned no records. Check {key_env} has access to this dataset.")
            metas = (meta.get("metas") or {}).get("default") or {}
            manifest.add(save(pd.DataFrame(rows), ds, metas, out_dir))
