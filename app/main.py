"""Minimal FastAPI app for GitHub → Render deploys."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="App", version=__version__)

if STATIC.is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC / "assets")), name="assets")


@app.get("/")
async def index():
    index_path = STATIC / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    return {"ok": True, "version": __version__}


@app.get("/health")
@app.get("/healthz")
async def health():
    return {
        "ok": True,
        "version": __version__,
        "service": os.getenv("RENDER_SERVICE_NAME", "local"),
        "env": os.getenv("APP_ENV", "development"),
    }


@app.get("/api/info")
async def info():
    return {
        "ok": True,
        "version": __version__,
        "stack": ["python", "fastapi", "docker", "github", "render"],
        "message": "Deployed from GitHub to Render.",
    }
