from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TrackedPerson(Base):
    """A ByteTrack identity inside one video (video-local, not a real-world identity)."""

    __tablename__ = "tracked_persons"
    __table_args__ = (UniqueConstraint("video_id", "tracking_id", name="uq_tracked_person_video_tracking"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    tracking_id: Mapped[int] = mapped_column(Integer)
    first_detected_frame: Mapped[int] = mapped_column(Integer)
    last_detected_frame: Mapped[int] = mapped_column(Integer)
    total_detected_frames: Mapped[int] = mapped_column(Integer, default=0)
    first_detected_timestamp: Mapped[float] = mapped_column(Float)
    last_detected_timestamp: Mapped[float] = mapped_column(Float)
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    video = relationship("Video", back_populates="tracked_persons")
