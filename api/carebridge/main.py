"""App factory. Run with `uvicorn carebridge.main:app --reload` from api/."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api.errors import register_error_handlers
from .api.middleware import RequestIdMiddleware
from .api.routes import ask, health, plan, reviews, tracts
from .config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    app = FastAPI(
        title="CareBridge gateway",
        version=__version__,
        description="Plans four Saturday mobile clinic stops and returns the Clinic Plan the UI renders.",
        docs_url=None if settings.env == "prod" else "/docs",
    )
    app.state.settings = settings

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex if settings.env != "prod" else None,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
        expose_headers=["X-Request-Id"],
    )
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(plan.router, prefix="/v1")
    app.include_router(tracts.router, prefix="/v1")
    app.include_router(ask.router, prefix="/v1")
    app.include_router(reviews.router, prefix="/v1")
    return app


app = create_app()
