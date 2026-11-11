"""Start/cancel processing and report progress (JSON + Server-Sent Events)."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import SessionLocal, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import resolve_managed_path
from app.models import DetectionSession, ProcessingStatus, Video
from app.schemas import MessageOut, ProcessRequest, ProgressOut
from app.services.video_processing_service import ProcessingOptions
from app.services.video_service import ensure_disk_space, get_video
from app.workers.video_worker import TERMINAL, worker

router = APIRouter(prefix="/api/videos", tags=["processing"])

SSE_MAX_SECONDS = 25


@router.post("/{video_id}/process", response_model=ProgressOut, status_code=202)
def start_processing(video_id: int, body: ProcessRequest | None = Body(None), db: Session = Depends(get_db)):
    body = body or ProcessRequest()
    video = get_video(db, video_id)
    if worker.is_active(video_id) or video.processing_status in {s.value for s in ProcessingStatus.active()}:
        raise ConflictError("This video is already queued or being processed.")
    if not resolve_managed_path(video.original_video_path).is_file():
        raise NotFoundError("The original video file is missing from local storage.")
    ensure_disk_space(settings.processed_dir, video.file_size)

    options = ProcessingOptions(
        model_name=body.model_name, confidence=body.confidence, frame_skip=body.frame_skip,
        show_boxes=body.show_boxes, show_ids=body.show_ids, show_confidence=body.show_confidence,
    )
    session = DetectionSession(
        video_id=video.id, model_name=body.model_name, tracker_name=settings.tracker_config,
        confidence_threshold=body.confidence, frame_skip=body.frame_skip,
        status=ProcessingStatus.QUEUED.value, options=options.as_dict(),
    )
    db.add(session)
    video.processing_status = ProcessingStatus.QUEUED.value
    video.processing_percentage = 0.0
    video.error_message = None
    db.commit()

    task = worker.submit(video.id, session.id, options)
    return ProgressOut(**task.snapshot())


def _progress_from_db(video: Video) -> dict:
    return {
        "video_id": video.id, "status": video.processing_status,
        "percentage": video.processing_percentage, "frames_processed": video.frames_processed,
        "total_frames": video.total_frames, "detected_people": video.total_unique_persons,
        "message": video.error_message,
        "processing_fps": (video.frames_processed / video.processing_time)
        if video.processing_time and video.processing_status == ProcessingStatus.COMPLETED.value else None,
        "elapsed_seconds": video.processing_time,
    }


def current_progress(db: Session, video_id: int) -> dict:
    task = worker.get(video_id)
    if task is not None and task.status not in TERMINAL:
        return task.snapshot()
    return _progress_from_db(get_video(db, video_id))


@router.get("/{video_id}/progress", response_model=ProgressOut)
def get_progress(video_id: int, db: Session = Depends(get_db)):
    return ProgressOut(**current_progress(db, video_id))


@router.get("/{video_id}/progress/stream")
async def stream_progress(video_id: int, request: Request):
    """Server-Sent Events stream of progress updates until a terminal state."""
    with SessionLocal() as db:
        get_video(db, video_id)  # 404 early

    async def events():
        last_payload = None
        idle = 0.0
        started = time.monotonic()
        # Tell EventSource to reconnect quickly when a stream is closed below.
        yield "retry: 1000\n\n"
        while True:
            # Bounded stream lifetime: lets uvicorn shut down / --reload promptly
            # (it waits for open responses); the browser reconnects automatically.
            if time.monotonic() - started > SSE_MAX_SECONDS:
                return
            if await request.is_disconnected():
                return
            with SessionLocal() as db:
                data = ProgressOut(**current_progress(db, video_id)).model_dump()
            payload = json.dumps(data)
            if payload != last_payload:
                last_payload, idle = payload, 0.0
                yield f"event: progress\ndata: {payload}\n\n"
            elif idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
            if data["status"] in TERMINAL or data["status"] == ProcessingStatus.UPLOADED.value:
                yield f"event: end\ndata: {payload}\n\n"
                return
            await asyncio.sleep(0.5)
            idle += 0.5

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.post("/{video_id}/cancel", response_model=MessageOut)
def cancel_processing(video_id: int, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    if worker.cancel(video_id):
        return MessageOut(detail="Cancellation requested.")
    if video.processing_status in {s.value for s in ProcessingStatus.active()}:
        # Stale state (e.g. no live task): reset it.
        video.processing_status = ProcessingStatus.CANCELLED.value
        video.error_message = "Processing was cancelled."
        db.commit()
        return MessageOut(detail="Processing cancelled.")
    raise ConflictError("This video is not being processed.")
