"""Video upload, listing, details and deletion."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import MessageOut, VideoListOut, VideoOut
from app.services import video_service

router = APIRouter(prefix="/api/videos", tags=["videos"])


@router.post("/upload", response_model=VideoOut, status_code=status.HTTP_201_CREATED)
async def upload_video(
    file: UploadFile = File(...),
    allow_duplicate: bool = Form(False),
    db: Session = Depends(get_db),
):
    video = await video_service.save_upload(db, file, allow_duplicate=allow_duplicate)
    return video_service.to_out(video)


@router.get("", response_model=VideoListOut)
def list_videos(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None, max_length=100),
    db: Session = Depends(get_db),
):
    return video_service.list_videos(db, page, page_size, status, search)


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int, db: Session = Depends(get_db)):
    return video_service.to_out(video_service.get_video(db, video_id))


@router.delete("/{video_id}", response_model=MessageOut)
def delete_video(video_id: int, db: Session = Depends(get_db)):
    video_service.delete_video(db, video_id)
    return MessageOut(detail=f"Video #{video_id} deleted.")
