"""Analysis jobs: planning, runtime estimates, queueing, cancellation, deletion."""

from __future__ import annotations

import logging
import math
import shutil
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import utcnow
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import resolve_managed_path, to_relative
from app.db import (
    AnalysisJob,
    AnalysisJobModel,
    ExecutionStatus,
    JobStatus,
    ModelBenchmark,
    ModelStatus,
    Video,
    VideoStatus,
)
from app.schemas import AnalysisRequest, JobListOut, JobModelOut, JobOut, PlanOut, PlanStepOut, ProgressOut
from app.services.video_service import ensure_disk_space, get_video
from app.vision.frame_extractor import processing_size
from app.vision.model_executor import estimate_stages
from app.vision.model_registry import registry
from app.vision.pipeline_planner import Pipeline, plan_pipeline
from app.workers.job_queue import queue, read_worker_status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- estimates
def measured_seconds_per_frame(db: Session, device: str | None = None) -> dict[str, float]:
    """Benchmarks measured on this machine (latest model versions only)."""
    device = device or read_worker_status().get("device") or "cpu"
    rows = db.scalars(select(ModelBenchmark).where(ModelBenchmark.device == device)).all()
    out = {}
    for r in rows:
        try:
            if registry.get_spec(r.model_id).version == r.model_version:
                out[r.model_id] = r.seconds_per_frame
        except KeyError:
            continue
    return out


def _plan(db: Session, req: AnalysisRequest) -> tuple[Video, Pipeline, PlanOut]:
    video = get_video(db, req.video_id)
    if video.status != VideoStatus.READY.value:
        raise ConflictError(f"The video is not ready for analysis (status: {video.status}).")
    pipeline = plan_pipeline(req.models, req.configs)

    measured = measured_seconds_per_frame(db)
    total = video.total_frames or int((video.duration or 0) * (video.fps or 25))
    width, height = processing_size(video.width or 0, video.height or 0, settings.max_inference_height)
    stages = estimate_stages(pipeline, total, req.options.frame_interval, width, height,
                             req.options.render_video, measured)

    warnings: list[str] = []
    for step in pipeline.steps:
        status, detail = registry.status_of(step.spec)
        if status == ModelStatus.NOT_DOWNLOADED.value:
            warnings.append(f"{step.spec.name}: {detail} The first run takes longer.")
        elif status == ModelStatus.WEIGHTS_MISSING.value:
            warnings.append(f"{step.spec.name}: {detail}")
    auto = [s.model_id for s in pipeline.steps if s.auto_added]
    if auto:
        names = ", ".join(registry.get_spec(m).name for m in auto)
        warnings.append(f"Added automatically because the selected models need their output: {names}.")
    if req.options.frame_interval > 3 and any(s.model_id == "human_tracking" for s in pipeline.steps):
        warnings.append("A frame interval above 3 makes tracking IDs less stable.")
    video_info = {"width": video.width, "height": video.height, "fps": video.fps,
                  "duration": video.duration, "total_frames": video.total_frames}
    for step in pipeline.steps:
        try:
            warnings.extend(registry.get_class(step.model_id).advice(step.config, video_info))
        except Exception:  # advice is optional; never block planning
            logger.exception("advice() failed for %s", step.model_id)
    if video.height and video.height > settings.max_inference_height:
        warnings.append(f"Frames are downscaled from {video.height}p to {settings.max_inference_height}p for "
                        "inference.")

    plan = PlanOut(
        steps=[PlanStepOut(**d) for d in pipeline.describe()],
        auto_added=auto,
        frames_to_process=math.ceil(total / req.options.frame_interval),
        estimated_seconds=round(sum(stages.values()), 1),
        estimate_breakdown={k: round(v, 1) for k, v in stages.items()},
        estimate_measured=all(s.model_id in measured for s in pipeline.steps),
        warnings=warnings,
    )
    return video, pipeline, plan


def plan_analysis(db: Session, req: AnalysisRequest) -> PlanOut:
    return _plan(db, req)[2]


# --------------------------------------------------------------------- jobs
def start_analysis(db: Session, req: AnalysisRequest) -> AnalysisJob:
    video, pipeline, plan = _plan(db, req)
    resolve_managed_path(video.file_path)  # confined path check
    ensure_disk_space(settings.results_dir, video.file_size)
    job = AnalysisJob(
        video_id=video.id, status=JobStatus.QUEUED.value, progress=0.0, current_stage="Queued",
        options={**req.options.model_dump(mode="json"), "selected_models": req.models,
                 "estimated_seconds": plan.estimated_seconds},
        progress_detail={}, summary={},
    )
    db.add(job)
    db.flush()
    for i, step in enumerate(pipeline.steps):
        db.add(AnalysisJobModel(
            job_id=job.id, model_id=step.model_id, model_version=step.spec.version,
            configuration=step.config.model_dump(mode="json"), position=i, auto_added=step.auto_added,
            execution_status=ExecutionStatus.PENDING.value, weights_sha256={},
        ))
    job.results_path = to_relative(settings.results_dir / str(job.id))
    db.commit()
    queue.enqueue(job.id)
    logger.info("Queued analysis job #%s for video #%s: %s", job.id, video.id, pipeline.model_ids)
    return job


def get_job(db: Session, job_id: int) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None:
        raise NotFoundError(f"Analysis job #{job_id} not found.")
    return job


def _file_ok(stored: str | None) -> bool:
    if not stored:
        return False
    try:
        return resolve_managed_path(stored).is_file()
    except Exception:
        return False


def job_to_out(db: Session, job: AnalysisJob) -> JobOut:
    models = []
    for m in job.models:
        out = JobModelOut.model_validate(m)
        try:
            out.name = registry.get_spec(m.model_id).name
        except KeyError:
            out.name = m.model_id
        models.append(out)
    video = db.get(Video, job.video_id)
    return JobOut(
        id=job.id, video_id=job.video_id, video_filename=video.filename if video else None,
        status=job.status, progress=job.progress, current_stage=job.current_stage,
        progress_detail=job.progress_detail or {}, options=job.options or {}, summary=job.summary or {},
        device=job.device, error_message=job.error_message, queued_at=job.queued_at,
        started_at=job.started_at, completed_at=job.completed_at,
        has_annotated_video=job.status == JobStatus.COMPLETED.value and _file_ok(job.annotated_video_path),
        queue_position=queue.position(job.id) if job.status == JobStatus.QUEUED.value else None,
        models=models,
    )


def list_jobs(db: Session, page: int, page_size: int, status: str | None = None,
              video_id: int | None = None) -> JobListOut:
    query = select(AnalysisJob)
    count = select(func.count(AnalysisJob.id))
    if status:
        query, count = query.where(AnalysisJob.status == status), count.where(AnalysisJob.status == status)
    if video_id:
        query, count = query.where(AnalysisJob.video_id == video_id), count.where(AnalysisJob.video_id == video_id)
    total = db.scalar(count) or 0
    rows = db.scalars(query.order_by(AnalysisJob.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return JobListOut(items=[job_to_out(db, j) for j in rows], total=total, page=page, page_size=page_size,
                      pages=max(1, math.ceil(total / page_size)))


def progress_of(db: Session, job_id: int) -> ProgressOut:
    job = get_job(db, job_id)
    db.refresh(job)
    return ProgressOut(
        job_id=job.id, status=job.status, progress=job.progress, current_stage=job.current_stage,
        detail=job.progress_detail or {}, error_message=job.error_message,
        queue_position=queue.position(job.id) if job.status == JobStatus.QUEUED.value else None,
        models=[{"model_id": m.model_id, "execution_status": m.execution_status,
                 "execution_time": m.execution_time, "error_message": m.error_message} for m in job.models],
    )


def cancel_job(db: Session, job_id: int) -> str:
    job = get_job(db, job_id)
    # Queued: cancel immediately (atomic, in case a worker claims it at the same moment).
    res = db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id,
                                               AnalysisJob.status == JobStatus.QUEUED.value)
                     .values(status=JobStatus.CANCELLED.value, completed_at=utcnow(),
                             current_stage="Cancelled", error_message="Cancelled before it started."))
    if res.rowcount:
        db.execute(update(AnalysisJobModel).where(AnalysisJobModel.job_id == job_id)
                   .values(execution_status=ExecutionStatus.CANCELLED.value))
        db.commit()
        return "Analysis cancelled."
    db.refresh(job)
    if job.status == JobStatus.PROCESSING.value:
        job.cancel_requested = True
        db.commit()
        return "Cancellation requested; the worker stops at the next frame."
    raise ConflictError(f"The analysis is already {job.status}.")


def remove_job_files(job: AnalysisJob) -> None:
    shutil.rmtree(settings.results_dir / str(job.id), ignore_errors=True)
    shutil.rmtree(settings.exports_dir / str(job.id), ignore_errors=True)


def delete_job(db: Session, job_id: int) -> None:
    job = get_job(db, job_id)
    if job.status in JobStatus.active():
        raise ConflictError("Cancel the analysis before deleting it.")
    remove_job_files(job)
    db.delete(job)
    db.commit()


def cleanup_old_results(db: Session, days: int) -> int:
    """Delete finished jobs (results, exports, DB rows) older than ``days``."""
    cutoff = utcnow() - timedelta(days=days)
    jobs = db.scalars(select(AnalysisJob).where(
        AnalysisJob.status.in_(JobStatus.terminal()),
        func.coalesce(AnalysisJob.completed_at, AnalysisJob.queued_at) < cutoff)).all()
    for job in jobs:
        remove_job_files(job)
        db.delete(job)
    db.commit()
    return len(jobs)
