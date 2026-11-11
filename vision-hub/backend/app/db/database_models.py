"""SQLAlchemy ORM models.

Detailed per-frame model outputs are NOT stored here: they live in chunked
result files (see ``app.vision.result_store``). The database keeps videos, the
model catalogue, jobs, and the summaries the dashboard queries.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class VideoStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    SCANNING = "scanning"
    READY = "ready"
    FAILED = "failed"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def active(cls) -> set[str]:
        return {cls.QUEUED.value, cls.PROCESSING.value}

    @classmethod
    def terminal(cls) -> set[str]:
        return {cls.COMPLETED.value, cls.FAILED.value, cls.CANCELLED.value}


class ExecutionStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"      # a dependency failed
    CANCELLED = "cancelled"


class ModelStatus(str, enum.Enum):
    AVAILABLE = "available"              # weights present (or none needed)
    NOT_DOWNLOADED = "not_downloaded"    # will be downloaded on first use
    WEIGHTS_MISSING = "weights_missing"  # missing and downloads are disabled
    ERROR = "error"
    DISABLED = "disabled"


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))                # display name
    stored_filename: Mapped[str] = mapped_column(String(64), unique=True)
    file_path: Mapped[str] = mapped_column(String(512))
    playback_path: Mapped[str | None] = mapped_column(String(512))    # H.264 copy when needed
    thumbnail_path: Mapped[str | None] = mapped_column(String(512))
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    duration: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    total_frames: Mapped[int | None] = mapped_column(Integer)
    codec: Mapped[str | None] = mapped_column(String(64))
    container: Mapped[str | None] = mapped_column(String(32))
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default=VideoStatus.UPLOADED.value, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    jobs: Mapped[list[AnalysisJob]] = relationship(back_populates="video", cascade="all, delete-orphan",
                                                    passive_deletes=True)


class VisionModel(Base):
    """Catalogue entry, synced from the plugin registry at startup (code is the source of truth)."""

    __tablename__ = "vision_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    weights_info: Mapped[list] = mapped_column(JSON, default=list)
    config_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    default_config: Mapped[dict] = mapped_column(JSON, default=dict)
    requires: Mapped[list] = mapped_column(JSON, default=list)
    produces: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default=ModelStatus.AVAILABLE.value)
    status_detail: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.QUEUED.value, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[str | None] = mapped_column(String(128))
    progress_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)     # job-level: frame interval, export...
    summary: Mapped[dict] = mapped_column(JSON, default=dict)     # totals computed at completion
    device: Mapped[str | None] = mapped_column(String(32))
    annotated_video_path: Mapped[str | None] = mapped_column(String(512))
    results_path: Mapped[str | None] = mapped_column(String(512))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    queued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)

    video: Mapped[Video] = relationship(back_populates="jobs")
    models: Mapped[list[AnalysisJobModel]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True,
        order_by="AnalysisJobModel.position",
    )


class AnalysisJobModel(Base):
    __tablename__ = "analysis_job_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    model_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    weights_sha256: Mapped[dict] = mapped_column(JSON, default=dict)   # file name -> sha256
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)           # execution order
    auto_added: Mapped[bool] = mapped_column(Boolean, default=False)
    execution_status: Mapped[str] = mapped_column(String(20), default=ExecutionStatus.PENDING.value)
    execution_time: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(String(512))

    job: Mapped[AnalysisJob] = relationship(back_populates="models")

    __table_args__ = (UniqueConstraint("job_id", "model_id"),)


class TrackedPerson(Base):
    __tablename__ = "tracked_persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)
    frame_count: Mapped[int] = mapped_column(Integer)
    avg_confidence: Mapped[float] = mapped_column(Float)
    trajectory: Mapped[list] = mapped_column(JSON, default=list)   # downsampled [t, cx, cy]

    __table_args__ = (UniqueConstraint("job_id", "track_id"),)


class ActivitySegment(Base):
    __tablename__ = "activity_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"))
    model_id: Mapped[str] = mapped_column(String(64))
    track_id: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(64))

    __table_args__ = (Index("ix_activity_job_track", "job_id", "track_id"),)


class FrameStat(Base):
    __tablename__ = "frame_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True)
    frame_number: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[float] = mapped_column(Float)
    people_count: Mapped[int] = mapped_column(Integer)


class ModelBenchmark(Base):
    """Measured inference cost per model on this machine, used for runtime estimates."""

    __tablename__ = "model_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(32))
    device: Mapped[str] = mapped_column(String(32))
    seconds_per_frame: Mapped[float] = mapped_column(Float)
    samples: Mapped[int] = mapped_column(Integer, default=1)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("model_id", "model_version", "device"),)
