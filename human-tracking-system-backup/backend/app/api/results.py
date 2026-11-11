"""Results, video streaming/download and CSV export."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import resolve_managed_path, sanitize_display_name
from app.models import ProcessingStatus
from app.schemas import ResultsOut
from app.services import analytics_service
from app.services.video_processing_service import download_name
from app.services.video_service import get_video

router = APIRouter(prefix="/api/videos", tags=["results"])

_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".mkv": "video/x-matroska"}


@router.get("/{video_id}/results", response_model=ResultsOut)
def get_results(video_id: int, db: Session = Depends(get_db)):
    return analytics_service.build_results(db, video_id)


@router.get("/{video_id}/original")
def get_original(video_id: int, download: bool = False, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    path = resolve_managed_path(video.original_video_path)
    if not path.is_file():
        raise NotFoundError("The original video file is missing.")
    media = _MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path, media_type=media, filename=sanitize_display_name(video.original_filename),
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{video_id}/processed")
def get_processed(video_id: int, download: bool = False, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    if video.processing_status != ProcessingStatus.COMPLETED.value or not video.processed_video_path:
        raise ConflictError("The processed video is not available yet.")
    path = resolve_managed_path(video.processed_video_path)
    if not path.is_file():
        raise NotFoundError("The processed video file is missing.")
    return FileResponse(
        path, media_type="video/mp4", filename=download_name(video),
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/{video_id}/export/csv")
def export_csv(
    video_id: int,
    type: str = Query("persons", pattern="^(persons|events)$"),
    db: Session = Depends(get_db),
):
    video = get_video(db, video_id)
    if video.processing_status != ProcessingStatus.COMPLETED.value:
        raise ConflictError("Statistics are available after processing completes.")
    stem = Path(sanitize_display_name(video.original_filename)).stem
    if type == "events":
        content, name = analytics_service.events_csv(db, video_id), f"{stem}_detection_events.csv"
    else:
        content, name = analytics_service.persons_csv(db, video_id), f"{stem}_tracked_persons.csv"
    return StreamingResponse(
        content, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
