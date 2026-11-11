from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DetectionEvent(Base):
    """A single person box in a single frame — raw data for future analytics."""

    __tablename__ = "detection_events"
    __table_args__ = (Index("ix_detection_events_video_frame", "video_id", "frame_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"))
    tracked_person_id: Mapped[int] = mapped_column(
        ForeignKey("tracked_persons.id", ondelete="CASCADE"), index=True
    )
    frame_number: Mapped[int] = mapped_column(Integer)
    timestamp_seconds: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
