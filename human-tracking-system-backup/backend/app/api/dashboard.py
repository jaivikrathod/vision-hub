"""Dashboard statistics and system information."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.schemas import DashboardStats, SystemInfo
from app.services import analytics_service
from app.services.detection_service import cuda_info, installed_models, select_device
from app.vision.video_io import ffmpeg_executable

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    return analytics_service.dashboard_stats(db)


@router.get("/system/info", response_model=SystemInfo)
def get_system_info():
    cuda_ok, gpu = cuda_info()
    return SystemInfo(
        app_name=settings.app_name, version=settings.app_version, device=select_device(),
        cuda_available=cuda_ok, gpu_name=gpu, ffmpeg_available=ffmpeg_executable() is not None,
        allowed_models=settings.allowed_models, installed_models=installed_models(),
        default_model=settings.default_model, default_confidence=settings.default_confidence,
        default_frame_skip=settings.default_frame_skip, max_frame_skip=settings.max_frame_skip,
        max_upload_size_mb=settings.max_upload_size_mb, allowed_extensions=settings.allowed_extensions,
        max_concurrent_jobs=settings.max_concurrent_jobs, tracker=settings.tracker_config,
    )
