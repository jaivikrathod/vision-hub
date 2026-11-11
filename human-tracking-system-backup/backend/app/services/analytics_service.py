"""Results, dashboard statistics and CSV exports — all computed from stored data."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import DetectionEvent, DetectionSession, ProcessingStatus, TrackedPerson, Video
from app.schemas import (
    DashboardStats,
    DetectionSessionOut,
    DetectionStats,
    ResultsOut,
    TimelinePoint,
    TrackedPersonOut,
)
from app.services.video_service import get_video, to_out

TIMELINE_POINTS = 200


def latest_session(db: Session, video_id: int, completed_only: bool = False) -> DetectionSession | None:
    q = select(DetectionSession).where(DetectionSession.video_id == video_id)
    if completed_only:
        q = q.where(DetectionSession.status == ProcessingStatus.COMPLETED.value)
    return db.scalar(q.order_by(DetectionSession.id.desc()).limit(1))


def build_results(db: Session, video_id: int) -> ResultsOut:
    video = get_video(db, video_id)
    session = latest_session(db, video_id)
    persons = db.scalars(
        select(TrackedPerson).where(TrackedPerson.video_id == video_id).order_by(TrackedPerson.tracking_id)
    ).all()

    per_frame = db.execute(
        select(DetectionEvent.frame_number, func.count(DetectionEvent.id))
        .where(DetectionEvent.video_id == video_id)
        .group_by(DetectionEvent.frame_number)
        .order_by(DetectionEvent.frame_number)
    ).all()
    avg_conf = db.scalar(select(func.avg(DetectionEvent.confidence)).where(DetectionEvent.video_id == video_id))

    frames_processed = video.frames_processed or 0
    stride = (session.frame_skip + 1) if session else 1
    frames_analyzed = math.ceil(frames_processed / stride) if frames_processed else 0
    total_detections = sum(c for _, c in per_frame)
    fps = video.fps or 25.0

    durations = [
        p.last_detected_timestamp - p.first_detected_timestamp + stride / fps for p in persons
    ]
    stats = DetectionStats(
        total_detections=total_detections,
        average_confidence=round(avg_conf, 4) if avg_conf is not None else None,
        max_people_in_frame=max((c for _, c in per_frame), default=0),
        average_people_per_frame=round(total_detections / frames_analyzed, 3) if frames_analyzed else 0.0,
        frames_with_people=len(per_frame),
        frames_analyzed=frames_analyzed,
        average_track_duration_seconds=round(sum(durations) / len(durations), 2) if durations else None,
    )

    return ResultsOut(
        video=to_out(video),
        session=DetectionSessionOut.model_validate(session) if session else None,
        stats=stats,
        persons=[TrackedPersonOut.model_validate(p) for p in persons],
        timeline=_timeline(per_frame, frames_processed, stride, fps),
    )


def _timeline(per_frame: list, frames_processed: int, stride: int, fps: float) -> list[TimelinePoint]:
    """Average number of people per analyzed frame, bucketed into ≤ TIMELINE_POINTS points."""
    if frames_processed <= 0:
        return []
    analyzed = list(range(0, frames_processed, stride))
    buckets = min(TIMELINE_POINTS, len(analyzed))
    size = len(analyzed) / buckets
    counts = dict(per_frame)
    points = []
    for b in range(buckets):
        frames = analyzed[int(b * size): int((b + 1) * size)] or [analyzed[min(int(b * size), len(analyzed) - 1)]]
        total = sum(counts.get(f, 0) for f in frames)
        points.append(TimelinePoint(timestamp=round(frames[0] / fps, 3), people=round(total / len(frames), 3)))
    return points


def dashboard_stats(db: Session, recent: int = 6) -> DashboardStats:
    counts = dict(db.execute(select(Video.processing_status, func.count(Video.id)).group_by(Video.processing_status)).all())
    completed = select(Video).where(Video.processing_status == ProcessingStatus.COMPLETED.value).subquery()
    agg = db.execute(
        select(
            func.coalesce(func.sum(completed.c.total_unique_persons), 0),
            func.coalesce(func.sum(completed.c.processing_time), 0.0),
            func.coalesce(func.sum(completed.c.frames_processed), 0),
        )
    ).one()
    recent_rows = db.scalars(select(Video).order_by(Video.id.desc()).limit(recent)).all()
    return DashboardStats(
        total_videos=sum(counts.values()),
        completed_videos=counts.get(ProcessingStatus.COMPLETED.value, 0),
        failed_videos=counts.get(ProcessingStatus.FAILED.value, 0),
        processing_videos=counts.get(ProcessingStatus.PROCESSING.value, 0) + counts.get(ProcessingStatus.QUEUED.value, 0),
        total_unique_persons=int(agg[0]),
        total_processing_time=float(agg[1]),
        total_frames_processed=int(agg[2]),
        recent_videos=[to_out(v) for v in recent_rows],
    )


# ---------------------------------------------------------------------- CSV
def _rows_to_csv(rows: Iterator[list]) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    for i, row in enumerate(rows):
        writer.writerow(row)
        if i % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
    if buf.getvalue():
        yield buf.getvalue()


def persons_csv(db: Session, video_id: int) -> Iterator[str]:
    video = get_video(db, video_id)
    persons = db.scalars(
        select(TrackedPerson).where(TrackedPerson.video_id == video_id).order_by(TrackedPerson.tracking_id)
    ).all()

    def rows():
        yield ["video_id", "video_filename", "tracking_id", "first_detected_frame", "last_detected_frame",
               "first_detected_timestamp_s", "last_detected_timestamp_s", "visible_duration_s",
               "total_detected_frames", "average_confidence"]
        for p in persons:
            yield [video.id, video.original_filename, p.tracking_id, p.first_detected_frame, p.last_detected_frame,
                   f"{p.first_detected_timestamp:.3f}", f"{p.last_detected_timestamp:.3f}",
                   f"{p.last_detected_timestamp - p.first_detected_timestamp:.3f}",
                   p.total_detected_frames, f"{p.average_confidence:.4f}"]

    return _rows_to_csv(rows())


def events_csv(db: Session, video_id: int) -> Iterator[str]:
    get_video(db, video_id)
    stmt = (
        select(DetectionEvent.frame_number, DetectionEvent.timestamp_seconds, TrackedPerson.tracking_id,
               DetectionEvent.x1, DetectionEvent.y1, DetectionEvent.x2, DetectionEvent.y2, DetectionEvent.confidence)
        .join(TrackedPerson, TrackedPerson.id == DetectionEvent.tracked_person_id)
        .where(DetectionEvent.video_id == video_id)
        .order_by(DetectionEvent.frame_number, TrackedPerson.tracking_id)
        .execution_options(yield_per=2000)
    )

    def rows():
        # Own session: the request-scoped one is closed before streaming finishes.
        stream_db = SessionLocal()
        try:
            yield ["frame_number", "timestamp_s", "tracking_id", "x1", "y1", "x2", "y2", "confidence"]
            for r in stream_db.execute(stmt):
                yield list(r)
        finally:
            stream_db.close()

    return _rows_to_csv(rows())
