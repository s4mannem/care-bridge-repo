"""Liveness and readiness. Cloud Run probes `/healthz`; `/readyz?deep=true` also pings BigQuery."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ... import __version__
from ...agents.runner import AgentRunner
from ...config import Settings
from ...data.bigquery import BigQueryRepo
from ..deps import get_app_settings, get_repo, get_runner

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
def readyz(
    settings: Annotated[Settings, Depends(get_app_settings)],
    repo: Annotated[BigQueryRepo, Depends(get_repo)],
    runner: Annotated[AgentRunner, Depends(get_runner)],
    deep: Annotated[bool, Query(description="Also run a query against BigQuery")] = False,
):
    checks = {
        "bigquery_configured": repo.configured,
        "agent_engine": runner.name,
    }
    ok = repo.configured
    if deep and repo.configured:
        try:
            repo.ping()
            checks["bigquery_reachable"] = True
        except Exception as exc:  # report, don't raise: this is a probe
            checks["bigquery_reachable"] = False
            checks["bigquery_error"] = type(exc).__name__
            ok = False
    body = {"status": "ready" if ok else "not_ready", "env": settings.env, "checks": checks}
    return JSONResponse(body, status_code=200 if ok else 503)
