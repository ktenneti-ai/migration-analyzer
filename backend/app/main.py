from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api.routes import (
    ingestion,
    lineage,
    metric_view,
    migration_plan,
    powerbi,
    projects,
    report,
    sql_conversion,
    teradata,
)
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Power BI / Teradata -> Databricks Migration Analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5180"],
    # The frontend normally reaches the API through Vite's same-origin /api
    # proxy, so this regex is a defensive fallback for GitHub Codespaces'
    # forwarded *.app.github.dev / *.githubpreview.dev port URLs.
    allow_origin_regex=r"https://.*\.(app\.github\.dev|githubpreview\.dev)",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(ingestion.router)
app.include_router(powerbi.router)
app.include_router(lineage.router)
app.include_router(report.router)
app.include_router(migration_plan.router)
app.include_router(sql_conversion.router)
app.include_router(metric_view.router)
app.include_router(teradata.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# TEMPORARY — Codespaces diagnostic only, remove once the frontend startup
# issue is resolved. Exposes .devcontainer/start.sh's own logs without
# requiring SSH (which itself has been unreliable in this repo's Codespaces
# environment) so a startup failure can be read from outside the container
# via the already-working backend port. Read-only, no user input beyond
# picking one of three fixed filenames.
_DEBUG_LOG_FILES = {"frontend", "backend", "start"}


@app.get("/api/_debug/log/{name}", response_class=PlainTextResponse)
def _debug_log(name: str):
    if name not in _DEBUG_LOG_FILES:
        return f"unknown log {name!r}; choose one of {sorted(_DEBUG_LOG_FILES)}"
    path = f"/tmp/migration-analyzer-logs/{name}.log"
    if not os.path.exists(path):
        return f"{path} does not exist"
    with open(path) as f:
        return f.read()
