"""FastAPI dependencies. Override these in tests with `app.dependency_overrides`."""
from fastapi import Request

from ..agents.runner import AgentRunner, build_runner
from ..config import Settings
from ..data.bigquery import BigQueryRepo
from ..data.reviews import ReviewStore, build_review_store


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


def get_review_store(request: Request) -> ReviewStore:
    app = request.app
    if not hasattr(app.state, "reviews"):
        app.state.reviews = build_review_store(app.state.settings)
    return app.state.reviews
