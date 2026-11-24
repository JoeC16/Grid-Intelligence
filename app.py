"""Vercel entrypoint: the API under /api and the built web app at /.

Locally you can run the same thing with:
    cd web && npm run build && cd .. && uv run uvicorn app:app --port 8000
(For development, run backend.main and the Vite dev server separately; see README.)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.main import app as api_app

DIST = (Path(__file__).resolve().parent / "web" / "dist").resolve()

app = FastAPI(title="Grid Intelligence", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api_app)

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def web(path: str) -> FileResponse:
    """Serve a file from the built web app, or index.html for app routes."""
    if not (DIST / "index.html").is_file():
        raise HTTPException(status_code=404, detail="Web app not built: run `npm run build` in web/.")
    target = (DIST / path).resolve()
    if path and target.is_file() and DIST in target.parents:  # no escaping the dist folder
        return FileResponse(target)
    return FileResponse(DIST / "index.html")
