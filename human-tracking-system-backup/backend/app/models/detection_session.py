from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DetectionSession(Base):
    """One processing run of a video with a given configuration."""

    __tablename__ = "detection_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    model_name: Mapped[str] = mapped_column(String(100))
    tracker_name: Mapped[str] = mapped_column(String(100))
    confidence_threshold: Mapped[float] = mapped_column(Float)
    frame_skip: Mapped[int] = mapped_column(Integer, default=0)
    device: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    options: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_detections: Mapped[int] = mapped_column(Integer, default=0)
    total_unique_persons: Mapped[int] = mapped_column(Integer, default=0)
    total_frames_processed: Mapped[int] = mapped_column(Integer, default=0)
    average_processing_fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video = relationship("Video", back_populates="sessions")
