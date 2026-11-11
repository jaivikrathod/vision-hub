"""FastAPI application entry point (API process).

Run from the backend/ directory:
    uvicorn app.main:app --reload --port 8000

Analyses run in a separate worker process:
    python -m app.workers.analysis_worker
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, dashboard, models, videos
from app.config import settings
from app.core.database import run_migrations, session_scope
from app.core.exceptions import register_exception_handlers
from app.services.video_service import resume_pending_scans
from app.vision.model_registry import registry

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("app")


def _clean_temp_dir() -> None:
    for f in settings.temp_dir.iterdir():
        if f.is_file() and f.name.startswith("upload-"):
            f.unlink(missing_ok=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_directories()
    run_migrations()
    with session_scope() as db:
        registry.sync_to_db(db)
    _clean_temp_dir()
    resume_pending_scans()
    logger.info("%s v%s API ready (models: %s)", settings.app_name, settings.app_version,
                ", ".join(registry.ids()))
    yield


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Range", "Accept-Ranges"],
)
register_exception_handlers(app)

for router in (videos.router, models.router, analysis.router, dashboard.router):
    app.include_router(router)
