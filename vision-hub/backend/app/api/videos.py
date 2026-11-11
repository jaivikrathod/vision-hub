"""Video upload, listing, details, streaming, thumbnail and deletion."""

from __future__ import annotations

import mimetypes

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.core.security import resolve_managed_path, sanitize_display_name
from app.schemas import MessageOut, VideoListOut, VideoOut
from app.services import video_service

router = APIRouter(prefix="/api/videos", tags=["videos"])

_MIME = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".mkv": "video/x-matroska"}


@router.post("/upload", response_model=VideoOut, status_code=status.HTTP_201_CREATED)
async def upload_video(file: UploadFile = File(...), allow_duplicate: bool = Form(False),
                       db: Session = Depends(get_db)):
    video = await video_service.save_upload(db, file, allow_duplicate=allow_duplicate)
    return video_service.to_out(db, video)


@router.get("", response_model=VideoListOut)
def list_videos(page: int = Query(1, ge=1), page_size: int = Query(12, ge=1, le=100),
                status: str | None = Query(None), search: str | None = Query(None, max_length=100),
                db: Session = Depends(get_db)):
    return video_service.list_videos(db, page, page_size, status, search)


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    return video_service.to_out(db, video_service.get_video(db, video_id))


@router.get("/{video_id}/stream")
def stream_video(video_id: int, db: Session = Depends(get_db)):
    """Browser-playable video (H.264 copy when one was made). Supports HTTP range requests."""
    video = video_service.get_video(db, video_id)
    path = video_service.playback_file(video)
    media = _MIME.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media, content_disposition_type="inline",
                        filename=sanitize_display_name(video.filename))


@router.get("/{video_id}/download")
def download_original(video_id: int, db: Session = Depends(get_db)):
    video = video_service.get_video(db, video_id)
    path = resolve_managed_path(video.file_path)
    if not path.is_file():
        raise NotFoundError("The original video file is missing.")
    media = _MIME.get(path.suffix.lower()) or "application/octet-stream"
    return FileResponse(path, media_type=media, filename=sanitize_display_name(video.filename))


@router.get("/{video_id}/thumbnail")
def get_thumbnail(video_id: int, db: Session = Depends(get_db)):
    video = video_service.get_video(db, video_id)
    if not video_service.file_exists(video.thumbnail_path):
        raise NotFoundError("No thumbnail yet.")
    return FileResponse(resolve_managed_path(video.thumbnail_path), media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})


@router.delete("/{video_id}", response_model=MessageOut)
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video_service.delete_video(db, video_id)
    return MessageOut(detail=f"Video #{video_id} deleted.")
