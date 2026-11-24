"""Publish the built web app plus the map's start-up data as static files.

Usage:  uv run python -m backend.export_static      (after the pipeline run and `npm run build`)

Writes public/ (git-ignored): a copy of web/dist plus public/data/<name>.json for
the endpoints that only change when the data is rebuilt (meta, sites, bsps, gsps,
network, and each country's story and operators). On Vercel, files in public/ are served from the CDN, so
the first screen loads without waiting for the Python function to start. Each
file is exactly what the API returns (same code path, via a test client). The
web app falls back to the live API whenever a file is missing.
Site detail and the Ask box still go to the API.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"
PUBLIC = ROOT / "public"

# file name -> API path. Keep in step with STATIC in web/src/api.ts.
ENDPOINTS = {
    "meta": "/meta",
    "sites": "/sites",
    "bsps": "/bsps",
    "gsps": "/gsps",
}


def endpoints(client: TestClient) -> dict[str, str]:
    """ENDPOINTS plus, for each country in the data, its story (story-GB.json) and operators (operators-ES.json)."""
    out = dict(ENDPOINTS)
    for c in client.get("/meta").json().get("countries", []):
        out[f"story-{c['code']}"] = f"/story?country={c['code']}"
        out[f"operators-{c['code']}"] = f"/operators?country={c['code']}"
        out[f"network-{c['code']}"] = f"/network?country={c['code']}"
    return out


def export(public: Path = PUBLIC, dist: Path = DIST) -> dict[str, int]:
    if not (dist / "index.html").is_file():
        raise SystemExit(f"{dist} has no index.html: run `npm run build` in web/ first.")
    if public.exists():
        shutil.rmtree(public)
    shutil.copytree(dist, public)
    (public / "data").mkdir()
    sizes = {}
    with TestClient(app) as client:
        for name, path in endpoints(client).items():
            r = client.get(path)
            r.raise_for_status()
            body = json.dumps(r.json(), separators=(",", ":"))
            (public / "data" / f"{name}.json").write_text(body)
            sizes[name] = len(body)
    return sizes


def main() -> None:
    for name, n in export().items():
        print(f"  public/data/{name}.json  {n / 1e3:7.0f} kB")
    print(f"Wrote {PUBLIC}")


if __name__ == "__main__":
    main()
