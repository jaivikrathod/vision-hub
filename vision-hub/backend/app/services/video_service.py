"""Video storage: upload validation, scanning, listing and deletion.

Upload flow: stream to a temp file (size limit, SHA-256, magic-byte check) →
quick probe (decodes a frame, reads fps/size/duration, enforces the duration
limit) → stored with status ``scanning`` → background scan (codec/audio
inspection, thumbnail, H.264 playback copy when the browser can't play the
original) → ``ready``.
"""

from __future__ import annotations

import hashlib
import logging
import math
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import session_scope
from app.core.exceptions import (
    ConflictError,
    DuplicateVideoError,
    EmptyVideoError,
    FileTooLargeError,
    InsufficientDiskSpaceError,
    NotFoundError,
    VideoTooLongError,
)
from app.core.security import (
    generate_stored_filename,
    resolve_managed_path,
    sanitize_display_name,
    to_relative,
    validate_content,
    validate_extension,
)
from app.db import AnalysisJob, JobStatus, Video, VideoStatus
from app.schemas import VideoListOut, VideoOut
from app.vision.video_io import probe_video
from app.vision.video_processor import inspect_streams, make_thumbnail, needs_playback_copy, transcode_for_playback

logger = logging.getLogger(__name__)

# One scan at a time: transcoding is CPU heavy and the worker may be busy too.
_scan_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-scan")
_scanning: set[int] = set()
_scan_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
def free_disk_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def ensure_disk_space(path: Path, needed_bytes: int = 0) -> None:
    free = free_disk_bytes(path)
    if free - needed_bytes < settings.min_free_disk_mb * 1024 * 1024:
        raise InsufficientDiskSpaceError(
            f"Not enough free disk space ({free / 1024**3:.2f} GB free). "
            "Delete old videos or results and try again."
        )


def file_exists(stored: str | None) -> bool:
    if not stored:
        return False
    try:
        return resolve_managed_path(stored).is_file()
    except Exception:
        return False


def remove_file(stored: str | None) -> None:
    if not stored:
        return
    try:
        resolve_managed_path(stored).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Could not remove file %s: %s", stored, exc)


def to_out(db: Session, video: Video) -> VideoOut:
    out = VideoOut.model_validate(video)
    out.has_thumbnail = file_exists(video.thumbnail_path)
    out.uses_playback_copy = bool(video.playback_path)
    out.job_count = db.scalar(select(func.count(AnalysisJob.id)).where(AnalysisJob.video_id == video.id)) or 0
    latest = db.execute(
        select(AnalysisJob.id, AnalysisJob.status).where(AnalysisJob.video_id == video.id)
        .order_by(AnalysisJob.id.desc()).limit(1)
    ).first()
    if latest:
        out.latest_job_id, out.latest_job_status = latest
    return out


def playback_file(video: Video) -> Path:
    """The file the browser should play: the H.264 copy if one exists, else the original."""
    stored = video.playback_path if file_exists(video.playback_path) else video.file_path
    path = resolve_managed_path(stored)
    if not path.is_file():
        raise NotFoundError("The video file is missing from local storage.")
    return path


# ------------------------------------------------------------------- upload
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
                    f"This video was already uploaded as '{existing.filename}' (video #{existing.id}).",
                    extra={"existing_video_id": existing.id},
                )

        meta = await run_in_threadpool(probe_video, tmp_path)  # raises on corrupt/empty videos
        if meta.duration > settings.max_video_duration_seconds:
            raise VideoTooLongError(
                f"The video is {meta.duration / 60:.1f} minutes long; the limit is "
                f"{settings.max_video_duration_seconds / 60:.0f} minutes (MAX_VIDEO_DURATION_SECONDS)."
            )

        stored = generate_stored_filename(ext)
        final_path = settings.upload_dir / stored
        shutil.move(str(tmp_path), final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    video = Video(
        filename=display_name, stored_filename=stored, file_path=to_relative(final_path),
        file_size=size, file_hash=file_hash, duration=meta.duration, fps=meta.fps,
        width=meta.width, height=meta.height, total_frames=meta.total_frames,
        status=VideoStatus.SCANNING.value,
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
    schedule_scan(video.id)
    return video


# --------------------------------------------------------------------- scan
def schedule_scan(video_id: int) -> None:
    with _scan_lock:
        if video_id in _scanning:
            return
        _scanning.add(video_id)
    _scan_pool.submit(_scan_safe, video_id)


def _scan_safe(video_id: int) -> None:
    try:
        scan_video(video_id)
    except Exception:
        logger.exception("Scanning video #%s crashed", video_id)
    finally:
        with _scan_lock:
            _scanning.discard(video_id)


def scan_video(video_id: int) -> None:
    """Inspect streams, create the thumbnail and (if needed) the browser playback copy."""
    with session_scope() as db:
        video = db.get(Video, video_id)
        if video is None:
            return
        source = resolve_managed_path(video.file_path)
        stem = Path(video.stored_filename).stem
        duration = video.duration or 0.0
        video.status = VideoStatus.SCANNING.value
    try:
        info = inspect_streams(source)
        thumb = settings.thumbnail_dir / f"{stem}.jpg"
        make_thumbnail(source, thumb, duration)
        playback = None
        if needs_playback_copy(source, info):
            logger.info("Video #%s (%s/%s) is not browser-playable; creating H.264 copy",
                        video_id, source.suffix, info.codec)
            playback = settings.playback_dir / f"{stem}.mp4"
            transcode_for_playback(source, playback)
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc)
        logger.error("Scanning video #%s failed: %s", video_id, message)
        with session_scope() as db:
            video = db.get(Video, video_id)
            if video is not None:
                video.status = VideoStatus.FAILED.value
                video.error_message = f"Scanning failed: {message}"
        return
    with session_scope() as db:
        video = db.get(Video, video_id)
        if video is None:  # deleted while scanning
            thumb.unlink(missing_ok=True)
            if playback:
                playback.unlink(missing_ok=True)
            return
        video.codec = info.codec
        video.container = info.container
        video.has_audio = info.has_audio
        video.thumbnail_path = to_relative(thumb)
        video.playback_path = to_relative(playback) if playback else None
        video.status = VideoStatus.READY.value
        video.error_message = None
    logger.info("Video #%s scanned (codec=%s, audio=%s, playback copy=%s)",
                video_id, info.codec, info.has_audio, bool(playback))


def resume_pending_scans() -> None:
    """Re-scan videos left in uploaded/scanning state (e.g. the API stopped mid-scan)."""
    with session_scope() as db:
        ids = db.scalars(select(Video.id).where(
            Video.status.in_([VideoStatus.UPLOADED.value, VideoStatus.SCANNING.value]))).all()
    for vid in ids:
        schedule_scan(vid)


# ------------------------------------------------------------- query/delete
def get_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError(f"Video #{video_id} not found.")
    return video


def list_videos(db: Session, page: int, page_size: int, status: str | None = None,
                search: str | None = None) -> VideoListOut:
    query = select(Video)
    count_query = select(func.count(Video.id))
    if status:
        query = query.where(Video.status == status)
        count_query = count_query.where(Video.status == status)
    if search:
        like = f"%{search}%"
        query = query.where(Video.filename.ilike(like))
        count_query = count_query.where(Video.filename.ilike(like))
    total = db.scalar(count_query) or 0
    rows = db.scalars(query.order_by(Video.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return VideoListOut(items=[to_out(db, v) for v in rows], total=total, page=page, page_size=page_size,
                        pages=max(1, math.ceil(total / page_size)))


def delete_video(db: Session, video_id: int) -> None:
    from app.services.analysis_service import remove_job_files

    video = get_video(db, video_id)
    active = db.scalar(select(func.count(AnalysisJob.id)).where(
        AnalysisJob.video_id == video_id, AnalysisJob.status.in_(JobStatus.active())))
    if active:
        raise ConflictError("This video has queued or running analyses. Cancel them before deleting it.")
    with _scan_lock:
        if video_id in _scanning:
            raise ConflictError("This video is still being scanned. Try again in a moment.")
    jobs = db.scalars(select(AnalysisJob).where(AnalysisJob.video_id == video_id)).all()
    files = [video.file_path, video.playback_path, video.thumbnail_path]
    for job in jobs:
        remove_job_files(job)
    db.delete(video)
    db.commit()
    for f in files:
        remove_file(f)
    logger.info("Deleted video #%s and %d analysis job(s)", video_id, len(jobs))
