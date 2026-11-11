"""Video storage: upload validation, persistence, listing and deletion."""

from __future__ import annotations

import hashlib
import logging
import math
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import (
    ConflictError,
    DuplicateVideoError,
    EmptyVideoError,
    FileTooLargeError,
    InsufficientDiskSpaceError,
    NotFoundError,
)
from app.core.security import (
    generate_stored_filename,
    resolve_managed_path,
    sanitize_display_name,
    to_relative,
    validate_content,
    validate_extension,
)
from app.models import DetectionEvent, DetectionSession, ProcessingStatus, TrackedPerson, Video
from app.schemas import VideoListOut, VideoOut
from app.vision.video_io import probe_video

logger = logging.getLogger(__name__)


def free_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def ensure_disk_space(path: Path, needed_bytes: int = 0) -> None:
    free = free_disk_bytes(path)
    if free - needed_bytes < settings.min_free_disk_mb * 1024 * 1024:
        raise InsufficientDiskSpaceError(
            f"Not enough free disk space ({free / 1024**3:.2f} GB free). "
            "Delete old videos or free up space and try again."
        )


def to_out(video: Video) -> VideoOut:
    out = VideoOut.model_validate(video)
    out.has_processed_video = bool(
        video.processed_video_path
        and video.processing_status == ProcessingStatus.COMPLETED.value
        and _exists(video.processed_video_path)
    )
    return out


def _exists(stored: str) -> bool:
    try:
        return resolve_managed_path(stored).is_file()
    except Exception:
        return False


async def save_upload(db: Session, upload: UploadFile, *, allow_duplicate: bool = False) -> Video:
    display_name = sanitize_display_name(upload.filename or "video")
    ext = validate_extension(upload.filename or "")

    declared = getattr(upload, "size", None)
    if declared is not None:
        if declared == 0:
            raise EmptyVideoError("The uploaded file is empty.")
        if declared > settings.max_upload_size_bytes:
            raise FileTooLargeError(f"File exceeds the {settings.max_upload_size_mb} MB upload limit.")
    ensure_disk_space(settings.upload_dir, declared or 0)

    tmp_path = settings.temp_dir / f"upload-{uuid.uuid4().hex}{ext}"
    hasher = hashlib.sha256()
    size = 0
    header = b""
    try:
        with tmp_path.open("wb") as out:
            while chunk := await upload.read(settings.upload_chunk_size):
                if len(header) < 64:
                    header += chunk[: 64 - len(header)]
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise FileTooLargeError(f"File exceeds the {settings.max_upload_size_mb} MB upload limit.")
                hasher.update(chunk)
                out.write(chunk)
        if size == 0:
            raise EmptyVideoError("The uploaded file is empty.")

        validate_content(ext, header)
        file_hash = hasher.hexdigest()

        if not allow_duplicate:
            existing = db.scalar(select(Video).where(Video.file_hash == file_hash).order_by(Video.id.desc()))
            if existing is not None:
                raise DuplicateVideoError(
                    f"This video was already uploaded as '{existing.original_filename}' (video #{existing.id}).",
                    extra={"existing_video_id": existing.id},
                )

        # raises on corrupted / empty videos; run off the event loop
        meta = await run_in_threadpool(probe_video, tmp_path)

        stored = generate_stored_filename(ext)
        final_path = settings.upload_dir / stored
        shutil.move(str(tmp_path), final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    video = Video(
        original_filename=display_name,
        stored_filename=stored,
        original_video_path=to_relative(final_path),
        file_size=size,
        file_hash=file_hash,
        duration=meta.duration,
        fps=meta.fps,
        width=meta.width,
        height=meta.height,
        total_frames=meta.total_frames,
        processing_status=ProcessingStatus.UPLOADED.value,
    )
    db.add(video)
    try:
        db.commit()
    except Exception:
        db.rollback()
        final_path.unlink(missing_ok=True)
        raise
    db.refresh(video)
    logger.info("Uploaded video #%s (%s, %.1f MB)", video.id, display_name, size / 1024**2)
    return video


def get_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError(f"Video #{video_id} not found.")
    return video


def list_videos(db: Session, page: int, page_size: int, status: str | None = None, search: str | None = None) -> VideoListOut:
    query = select(Video)
    count_query = select(func.count(Video.id))
    if status:
        query = query.where(Video.processing_status == status)
        count_query = count_query.where(Video.processing_status == status)
    if search:
        like = f"%{search}%"
        query = query.where(Video.original_filename.ilike(like))
        count_query = count_query.where(Video.original_filename.ilike(like))
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(Video.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return VideoListOut(
        items=[to_out(v) for v in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=max(1, math.ceil(total / page_size)),
    )


def clear_results(db: Session, video_id: int) -> None:
    """Remove tracking results of a video (before reprocessing or deletion)."""
    db.execute(delete(DetectionEvent).where(DetectionEvent.video_id == video_id))
    db.execute(delete(TrackedPerson).where(TrackedPerson.video_id == video_id))


def remove_file(stored: str | None) -> None:
    if not stored:
        return
    try:
        resolve_managed_path(stored).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Could not remove file %s: %s", stored, exc)


def delete_video(db: Session, video_id: int) -> None:
    video = get_video(db, video_id)
    if video.processing_status in {s.value for s in ProcessingStatus.active()}:
        raise ConflictError("This video is being processed. Cancel processing before deleting it.")
    original, processed = video.original_video_path, video.processed_video_path
    clear_results(db, video_id)
    db.execute(delete(DetectionSession).where(DetectionSession.video_id == video_id))
    db.delete(video)
    db.commit()
    remove_file(original)
    remove_file(processed)
    logger.info("Deleted video #%s", video_id)
