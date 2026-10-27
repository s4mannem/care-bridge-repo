"""FastAPI dependencies. Override these in tests with `app.dependency_overrides`."""
from fastapi import Request

from ..agents.runner import AgentRunner, build_runner
from ..config import Settings
from ..data.bigquery import BigQueryRepo


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_repo(request: Request) -> BigQueryRepo:
    app = request.app
    if not hasattr(app.state, "repo"):
        app.state.repo = BigQueryRepo(app.state.settings)
    return app.state.repo


def get_runner(request: Request) -> AgentRunner:
    app = request.app
    if not hasattr(app.state, "runner"):
        app.state.runner = build_runner(app.state.settings)
    return app.state.runner
