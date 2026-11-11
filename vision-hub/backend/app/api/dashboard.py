"""Dashboard summary and system information."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.core.exceptions import ValidationFailed
from app.schemas import DashboardOut, MessageOut, SystemInfoOut
from app.services import analysis_service, analytics_service
from app.workers.job_queue import read_worker_status

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    return analytics_service.dashboard(db)


@router.get("/system", response_model=SystemInfoOut, tags=["system"])
def system_info():
    worker = read_worker_status()
    return SystemInfoOut(
        app_name=settings.app_name, version=settings.app_version,
        device=worker.get("device") or settings.device, cuda_available=bool(worker.get("cuda_available")),
        cuda_device=worker.get("cuda_device"), torch_threads=worker.get("torch_threads") or settings.torch_threads,
        max_upload_size_mb=settings.max_upload_size_mb,
        max_video_duration_seconds=settings.max_video_duration_seconds,
        max_inference_height=settings.max_inference_height, max_loaded_models=settings.max_loaded_models,
        allowed_extensions=settings.allowed_extensions, results_retention_days=settings.results_retention_days,
        allow_model_download=settings.allow_model_download, worker=worker,
        disk_free_gb=round(shutil.disk_usage(settings.storage_dir).free / 1024**3, 2),
    )


@router.post("/system/cleanup", response_model=MessageOut, tags=["system"])
def cleanup(days: int | None = Query(None, ge=1, le=3650), db: Session = Depends(get_db)):
    """Delete finished analyses (results, exports) older than ``days`` (default RESULTS_RETENTION_DAYS)."""
    days = days or settings.results_retention_days
    if not days:
        raise ValidationFailed("Pass ?days=N or set RESULTS_RETENTION_DAYS.")
    n = analysis_service.cleanup_old_results(db, days)
    return MessageOut(detail=f"Deleted {n} analysis result(s) older than {days} day(s).")
