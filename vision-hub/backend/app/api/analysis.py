"""Analysis jobs: plan, start, list, progress (SSE), cancel, results and exports."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import resolve_managed_path, sanitize_display_name
from app.db import JobStatus, Video
from app.schemas import (
    ActivitiesOut,
    AnalysisRequest,
    FramesOut,
    JobListOut,
    JobOut,
    MessageOut,
    PersonOut,
    PlanOut,
    ProgressOut,
    ResultsOut,
)
from app.services import analysis_service, analytics_service

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

SSE_MAX_SECONDS = 25


@router.post("/plan", response_model=PlanOut)
def plan(req: AnalysisRequest, db: Session = Depends(get_db)):
    """Resolve the pipeline (auto-added models, order), validate configs and estimate runtime."""
    return analysis_service.plan_analysis(db, req)


@router.post("/start", response_model=JobOut, status_code=202)
def start(req: AnalysisRequest, db: Session = Depends(get_db)):
    job = analysis_service.start_analysis(db, req)
    return analysis_service.job_to_out(db, job)


@router.get("", response_model=JobListOut)
def list_jobs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
              status: str | None = Query(None), video_id: int | None = Query(None),
              db: Session = Depends(get_db)):
    return analysis_service.list_jobs(db, page, page_size, status, video_id)


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db)):
    return analysis_service.job_to_out(db, analysis_service.get_job(db, job_id))


@router.get("/{job_id}/progress")
async def progress(job_id: int, request: Request):
    """Server-Sent Events: ``progress`` events until the job ends, then one ``end`` event.

    Each connection lives at most ~25 s (so servers can restart promptly); the
    browser's EventSource reconnects automatically.
    """
    with SessionLocal() as db:
        analysis_service.get_job(db, job_id)  # 404 early

    async def events():
        last_payload = None
        idle = 0.0
        started = time.monotonic()
        yield "retry: 1000\n\n"
        while True:
            if time.monotonic() - started > SSE_MAX_SECONDS or await request.is_disconnected():
                return
            with SessionLocal() as db:
                data = analysis_service.progress_of(db, job_id).model_dump(mode="json")
            payload = json.dumps(data)
            if payload != last_payload:
                last_payload, idle = payload, 0.0
                yield f"event: progress\ndata: {payload}\n\n"
            elif idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
            if data["status"] in JobStatus.terminal():
                yield f"event: end\ndata: {payload}\n\n"
                return
            await asyncio.sleep(0.5)
            idle += 0.5

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{job_id}/status", response_model=ProgressOut)
def progress_snapshot(job_id: int, db: Session = Depends(get_db)):
    """Plain JSON progress (for polling clients)."""
    return analysis_service.progress_of(db, job_id)


@router.post("/{job_id}/cancel", response_model=MessageOut)
def cancel(job_id: int, db: Session = Depends(get_db)):
    return MessageOut(detail=analysis_service.cancel_job(db, job_id))


@router.delete("/{job_id}", response_model=MessageOut)
def delete(job_id: int, db: Session = Depends(get_db)):
    analysis_service.delete_job(db, job_id)
    return MessageOut(detail=f"Analysis #{job_id} deleted.")


@router.get("/{job_id}/results", response_model=ResultsOut)
def results(job_id: int, db: Session = Depends(get_db)):
    return analytics_service.build_results(db, job_id)


@router.get("/{job_id}/frames", response_model=FramesOut)
def frames(job_id: int, start: float = Query(0.0, ge=0), end: float = Query(10.0, ge=0),
           db: Session = Depends(get_db)):
    """Per-frame overlay data (boxes, IDs, keypoints, postures) for a time range of at most 60 s."""
    if end < start:
        raise ConflictError("'end' must be after 'start'.")
    return analytics_service.frames(db, job_id, start, end)


@router.get("/{job_id}/persons", response_model=list[PersonOut])
def persons(job_id: int, db: Session = Depends(get_db)):
    return analytics_service.persons(db, job_id)


@router.get("/{job_id}/activities", response_model=ActivitiesOut)
def activities(job_id: int, model_id: str | None = Query(None), db: Session = Depends(get_db)):
    return analytics_service.activities(db, job_id, model_id)


@router.get("/{job_id}/annotated-video")
def annotated_video(job_id: int, download: bool = False, db: Session = Depends(get_db)):
    job = analysis_service.get_job(db, job_id)
    if job.status != JobStatus.COMPLETED.value or not job.annotated_video_path:
        raise NotFoundError("No annotated video for this analysis (it may have been disabled).")
    path = resolve_managed_path(job.annotated_video_path)
    if not path.is_file():
        raise NotFoundError("The annotated video file is missing.")
    video = db.get(Video, job.video_id)
    stem = sanitize_display_name(video.filename).rsplit(".", 1)[0] if video else "video"
    return FileResponse(path, media_type="video/mp4", filename=f"{stem}_analysis_{job_id}.mp4",
                        content_disposition_type="attachment" if download else "inline")
