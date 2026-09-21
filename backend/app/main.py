from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    ingestion,
    lineage,
    metric_view,
    migration_plan,
    powerbi,
    projects,
    report,
    sql_conversion,
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
    allow_origins=["http://localhost:5173"],
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


@app.get("/api/health")
def health():
    return {"status": "ok"}
