"""Analytics built from stored inference results (never from mock data)."""

from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.exceptions import ConflictError
from app.db import ActivitySegment, AnalysisJob, FrameStat, JobStatus, ModelStatus, TrackedPerson, Video, VisionModel
from app.schemas import (
    ActivitiesOut,
    ActivityModelSummary,
    ActivitySegmentOut,
    DashboardOut,
    FrameOut,
    FramePersonOut,
    FramesOut,
    PersonOut,
    ResultsOut,
)
from app.services import video_service
from app.services.analysis_service import get_job, job_to_out
from app.vision import data_types as dt
from app.vision.activity_utils import UNCERTAIN
from app.vision.annotator import merge_persons
from app.vision.model_registry import registry
from app.vision.result_store import JobResultStore
from app.workers.job_queue import read_worker_status

MAX_FRAMES_WINDOW_SECONDS = 60.0
MAX_CHART_POINTS = 600


def _completed_job(db: Session, job_id: int) -> AnalysisJob:
    job = get_job(db, job_id)
    if job.status != JobStatus.COMPLETED.value:
        raise ConflictError(f"Results are available after the analysis completes (status: {job.status}).")
    return job


def _store(job: AnalysisJob) -> JobResultStore:
    return JobResultStore(settings.results_dir / str(job.id), settings.result_chunk_seconds)


def _model_name(model_id: str) -> str:
    try:
        return registry.get_spec(model_id).name
    except KeyError:
        return model_id


def activity_summaries(segments: list[ActivitySegment]) -> list[ActivityModelSummary]:
    by_model: dict[str, list[ActivitySegment]] = defaultdict(list)
    for s in segments:
        by_model[s.model_id].append(s)
    out = []
    for model_id, segs in sorted(by_model.items()):
        dist: dict[str, float] = defaultdict(float)
        for s in segs:
            dist[s.label] += s.end_time - s.start_time
        certain = [s for s in segs if s.label != UNCERTAIN]
        total_t = sum(s.end_time - s.start_time for s in certain)
        avg = (sum(s.confidence * (s.end_time - s.start_time) for s in certain) / total_t) if total_t else None
        out.append(ActivityModelSummary(
            model_id=model_id, name=_model_name(model_id),
            distribution_seconds={k: round(v, 2) for k, v in sorted(dist.items(), key=lambda kv: -kv[1])},
            average_confidence=round(avg, 3) if avg is not None else None, segment_count=len(segs)))
    return out


def build_results(db: Session, job_id: int) -> ResultsOut:
    job = _completed_job(db, job_id)
    video = db.get(Video, job.video_id)
    summary = job.summary or {}
    segments = db.scalars(select(ActivitySegment).where(ActivitySegment.job_id == job_id)).all()

    stats = db.execute(select(FrameStat.timestamp, FrameStat.people_count).where(FrameStat.job_id == job_id)
                       .order_by(FrameStat.frame_number)).all()
    if len(stats) > MAX_CHART_POINTS:
        # Keep the maximum of each bucket so short peaks stay visible.
        size = math.ceil(len(stats) / MAX_CHART_POINTS)
        stats = [max(stats[i:i + size], key=lambda r: r[1]) for i in range(0, len(stats), size)]

    model_ids = {m.model_id for m in job.models if m.execution_status == "completed"}
    produced = {t for m in model_ids for t in _produces(m)}
    overlays = []
    if dt.PERSON_DETECTIONS in produced:
        overlays += ["boxes", "confidence"]
    if dt.PERSON_TRACKS in produced:
        overlays.append("ids")
    if dt.PERSON_KEYPOINTS in produced:
        overlays.append("skeleton")
    if dt.POSTURE_LABELS in produced:
        overlays.append("posture")
    if dt.ACTIVITY_SEGMENTS in produced:
        overlays.append("activity")

    return ResultsOut(
        job=job_to_out(db, job), video=video_service.to_out(db, video),
        unique_people=summary.get("unique_people"),
        total_detections=summary.get("total_detections", 0),
        average_people_per_frame=summary.get("average_people_per_frame"),
        max_people_in_frame=summary.get("max_people_in_frame"),
        frames_processed=summary.get("frames_processed", 0),
        processing_seconds=summary.get("processing_seconds"),
        processing_fps=summary.get("processing_fps"),
        posture_distribution=summary.get("posture_distribution", {}),
        activity_models=activity_summaries(segments),
        people_over_time=[[round(t, 3), c] for t, c in stats],
        coord_width=summary.get("coord_width"), coord_height=summary.get("coord_height"),
        available_overlays=overlays,
    )


def _produces(model_id: str) -> list[str]:
    try:
        return registry.get_spec(model_id).produces
    except KeyError:
        return []


def frames(db: Session, job_id: int, start: float, end: float) -> FramesOut:
    """Per-frame overlay data for a time range (merged across the job's per-frame models)."""
    job = _completed_job(db, job_id)
    end = min(end, start + MAX_FRAMES_WINDOW_SECONDS)
    store = _store(job)
    frame_models = [m.model_id for m in job.models
                    if m.execution_status == "completed" and store.meta(m.model_id).get("kind") == "frame"]
    valid = {r for r in db.scalars(select(TrackedPerson.track_id).where(TrackedPerson.job_id == job_id))}
    has_tracking = any(dt.PERSON_TRACKS in _produces(m) for m in frame_models)
    meta = store.meta(frame_models[0]) if frame_models else {}
    out = []
    for f, t, data in store.iter_merged(frame_models, start, end):
        persons = merge_persons(data, valid if has_tracking else None)
        out.append(FrameOut(f=f, t=t, persons=[FramePersonOut(**p) for p in persons]))
    return FramesOut(start=start, end=end, coord_width=meta.get("coord_width"),
                     coord_height=meta.get("coord_height"), fps=meta.get("fps"),
                     frame_interval=meta.get("frame_interval", 1), frames=out)


def persons(db: Session, job_id: int) -> list[PersonOut]:
    _completed_job(db, job_id)
    people = db.scalars(select(TrackedPerson).where(TrackedPerson.job_id == job_id)
                        .order_by(TrackedPerson.track_id)).all()
    segs = db.scalars(select(ActivitySegment).where(ActivitySegment.job_id == job_id)
                      .order_by(ActivitySegment.track_id, ActivitySegment.start_time)).all()
    by_track: dict[int, list[ActivitySegment]] = defaultdict(list)
    for s in segs:
        by_track[s.track_id].append(s)
    out = []
    for p in people:
        mine = by_track.get(p.track_id, [])
        dominant: dict[str, str | None] = {}
        for model_id in {s.model_id for s in mine}:
            totals: dict[str, float] = defaultdict(float)
            for s in mine:
                if s.model_id == model_id and s.label != UNCERTAIN:
                    totals[s.label] += s.end_time - s.start_time
            dominant[model_id] = max(totals, key=totals.get) if totals else None
        out.append(PersonOut(
            track_id=p.track_id, first_seen=p.first_seen, last_seen=p.last_seen,
            duration=round(p.last_seen - p.first_seen, 3), frame_count=p.frame_count,
            avg_confidence=p.avg_confidence, trajectory=p.trajectory, dominant_activity=dominant,
            activities=[ActivitySegmentOut.model_validate(s) for s in mine]))
    return out


def activities(db: Session, job_id: int, model_id: str | None = None) -> ActivitiesOut:
    _completed_job(db, job_id)
    q = select(ActivitySegment).where(ActivitySegment.job_id == job_id)
    if model_id:
        q = q.where(ActivitySegment.model_id == model_id)
    segs = db.scalars(q.order_by(ActivitySegment.track_id, ActivitySegment.start_time)).all()
    return ActivitiesOut(segments=[ActivitySegmentOut.model_validate(s) for s in segs],
                         models=activity_summaries(segs))


def dashboard(db: Session) -> DashboardOut:
    from app.db import AnalysisJob as J

    videos_by_status = dict(db.execute(select(Video.status, func.count(Video.id)).group_by(Video.status)).all())
    jobs_by_status = dict(db.execute(select(J.status, func.count(J.id)).group_by(J.status)).all())
    total_models = db.scalar(select(func.count(VisionModel.id)).where(VisionModel.is_active.is_(True))) or 0
    available = db.scalar(select(func.count(VisionModel.id)).where(
        VisionModel.is_active.is_(True),
        VisionModel.status.in_([ModelStatus.AVAILABLE.value, ModelStatus.NOT_DOWNLOADED.value]))) or 0
    people = db.scalar(select(func.count(TrackedPerson.id))) or 0
    seconds = 0.0
    for (summary,) in db.execute(select(J.summary).where(J.status == JobStatus.COMPLETED.value)).all():
        seconds += (summary or {}).get("processing_seconds") or 0.0
    activity_totals: dict[str, float] = defaultdict(float)
    for label, dur in db.execute(select(ActivitySegment.label,
                                        func.sum(ActivitySegment.end_time - ActivitySegment.start_time))
                                 .where(ActivitySegment.label != UNCERTAIN)
                                 .group_by(ActivitySegment.label)).all():
        activity_totals[label] = round(dur or 0.0, 2)
    recent_jobs = db.scalars(select(J).order_by(J.id.desc()).limit(6)).all()
    recent_videos = db.scalars(select(Video).order_by(Video.id.desc()).limit(6)).all()
    return DashboardOut(
        total_videos=sum(videos_by_status.values()), videos_by_status=videos_by_status,
        total_jobs=sum(jobs_by_status.values()), jobs_by_status=jobs_by_status,
        total_models=total_models, available_models=available, people_tracked=people,
        total_processing_seconds=round(seconds, 1),
        recent_jobs=[job_to_out(db, j) for j in recent_jobs],
        recent_videos=[video_service.to_out(db, v) for v in recent_videos],
        worker=read_worker_status(), activity_totals=dict(activity_totals),
    )
