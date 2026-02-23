"""FastAPI app entrypoint for SAMS Web."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sams_web.config import get_settings
from sams_web.routers.api import router as api_router
from sams_web.routers.pages import router as pages_router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title, debug=settings.debug)

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(pages_router)
    app.include_router(api_router)
    return app


app = create_app()
