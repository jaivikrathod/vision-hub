"""Pydantic request/response schemas. Filesystem paths are never exposed."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import settings

__all__ = [
    "VideoOut", "VideoListOut", "ProcessRequest", "ProgressOut", "DetectionSessionOut",
    "TrackedPersonOut", "ResultsOut", "DetectionStats", "TimelinePoint", "DashboardStats", "SystemInfo",
    "MessageOut",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class VideoOut(ORMModel):
    id: int
    original_filename: str
    file_size: int
    duration: float | None
    fps: float | None
    width: int | None
    height: int | None
    total_frames: int | None
    processing_status: str
    processing_percentage: float
    total_unique_persons: int
    frames_processed: int
    processing_time: float | None
    error_message: str | None
    has_processed_video: bool = False
    created_at: datetime
    updated_at: datetime


class VideoListOut(BaseModel):
    items: list[VideoOut]
    total: int
    page: int
    page_size: int
    pages: int


class ProcessRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(default_factory=lambda: settings.default_model)
    confidence: float = Field(default_factory=lambda: settings.default_confidence, ge=0.05, le=0.95)
    frame_skip: int = Field(default_factory=lambda: settings.default_frame_skip, ge=0)
    show_boxes: bool = Field(default_factory=lambda: settings.show_boxes)
    show_ids: bool = Field(default_factory=lambda: settings.show_ids)
    show_confidence: bool = Field(default_factory=lambda: settings.show_confidence)

    @field_validator("model_name")
    @classmethod
    def _model_allowed(cls, v: str) -> str:
        if v not in settings.allowed_models:
            raise ValueError(f"model_name must be one of {settings.allowed_models}")
        return v

    @field_validator("frame_skip")
    @classmethod
    def _skip_range(cls, v: int) -> int:
        if v > settings.max_frame_skip:
            raise ValueError(f"frame_skip must be between 0 and {settings.max_frame_skip}")
        return v


class ProgressOut(BaseModel):
    video_id: int
    status: str
    percentage: float
    frames_processed: int
    total_frames: int | None
    detected_people: int
    people_in_frame: int = 0
    processing_fps: float | None = None
    eta_seconds: float | None = None
    elapsed_seconds: float | None = None
    device: str | None = None
    message: str | None = None


class DetectionSessionOut(ORMModel):
    id: int
    model_name: str
    tracker_name: str
    confidence_threshold: float
    frame_skip: int
    device: str | None
    status: str
    options: dict | None
    total_detections: int
    total_unique_persons: int
    total_frames_processed: int
    average_processing_fps: float | None
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    created_at: datetime


class TrackedPersonOut(ORMModel):
    tracking_id: int
    first_detected_frame: int
    last_detected_frame: int
    total_detected_frames: int
    first_detected_timestamp: float
    last_detected_timestamp: float
    average_confidence: float


class DetectionStats(BaseModel):
    total_detections: int
    average_confidence: float | None
    max_people_in_frame: int
    average_people_per_frame: float
    frames_with_people: int
    frames_analyzed: int
    average_track_duration_seconds: float | None


class TimelinePoint(BaseModel):
    timestamp: float
    people: float


class ResultsOut(BaseModel):
    video: VideoOut
    session: DetectionSessionOut | None
    stats: DetectionStats
    persons: list[TrackedPersonOut]
    timeline: list[TimelinePoint]


class DashboardStats(BaseModel):
    total_videos: int
    completed_videos: int
    failed_videos: int
    processing_videos: int
    total_unique_persons: int
    total_processing_time: float
    total_frames_processed: int
    recent_videos: list[VideoOut]


class SystemInfo(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    app_name: str
    version: str
    device: str
    cuda_available: bool
    gpu_name: str | None
    ffmpeg_available: bool
    allowed_models: list[str]
    installed_models: list[str]
    default_model: str
    default_confidence: float
    default_frame_skip: int
    max_frame_skip: int
    max_upload_size_mb: int
    allowed_extensions: list[str]
    max_concurrent_jobs: int
    tracker: str


class MessageOut(BaseModel):
    detail: str
