"""FastAPI application entry point.

Run from the backend/ directory:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import dashboard, processing, results, videos
from app.config import settings
from app.core.database import run_migrations
from app.core.exceptions import register_exception_handlers
from app.workers.video_worker import mark_interrupted, worker

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


def _clean_temp_dir() -> None:
    for f in settings.temp_dir.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_directories()
    run_migrations()
    mark_interrupted()  # jobs that were running when the app last stopped
    _clean_temp_dir()
    worker.start()
    logger.info("%s v%s ready", settings.app_name, settings.app_version)
    yield
    worker.stop()


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
register_exception_handlers(app)

for router in (videos.router, processing.router, results.router, dashboard.router):
    app.include_router(router)


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok"}
