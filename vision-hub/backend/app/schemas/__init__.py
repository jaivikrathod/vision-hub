"""Pydantic schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MessageOut(BaseModel):
    detail: str


# ------------------------------------------------------------------ videos
class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_size: int
    duration: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    total_frames: int | None = None
    codec: str | None = None
    container: str | None = None
    has_audio: bool = False
    status: str
    error_message: str | None = None
    created_at: datetime
    has_thumbnail: bool = False
    uses_playback_copy: bool = False
    job_count: int = 0
    latest_job_id: int | None = None
    latest_job_status: str | None = None


class VideoListOut(BaseModel):
    items: list[VideoOut]
    total: int
    page: int
    page_size: int
    pages: int


# ------------------------------------------------------------------ models
class WeightOut(BaseModel):
    name: str
    source: str
    kind: str
    size_mb: float | None = None
    license: str | None = None
    present: bool
    sha256: str | None = None


class ModelOut(BaseModel):
    model_id: str
    name: str
    category: str
    version: str
    description: str
    license: str
    kind: str
    requires: list[str]
    produces: list[str]
    input_types: list[str]
    output_descriptions: dict[str, str]
    weights: list[WeightOut]
    status: str
    status_detail: str | None = None
    neural: bool
    cost_hint: str
    labels: list[str]
    method: str
    limitations: list[str]
    seconds_per_frame: float
    seconds_per_frame_measured: bool
    providers: dict[str, list[str]] = Field(
        default_factory=dict, description="For each required data type, the models that can provide it")


class ModelDetailOut(ModelOut):
    config_schema: dict[str, Any]
    default_config: dict[str, Any]


class ModelConfigOut(BaseModel):
    model_id: str
    config_schema: dict[str, Any]
    default_config: dict[str, Any]


# ---------------------------------------------------------------- analysis
class OverlayOptionsIn(BaseModel):
    show_boxes: bool = True
    show_ids: bool = True
    show_skeleton: bool = True
    show_posture: bool = True
    show_activity: bool = True
    show_confidence: bool = False


class JobOptionsIn(BaseModel):
    frame_interval: int = Field(1, ge=1, le=30, description="Process every Nth frame (1 = every frame)")
    render_video: bool = Field(True, description="Also produce an annotated MP4 for download")
    overlay: OverlayOptionsIn = Field(default_factory=OverlayOptionsIn)


class AnalysisRequest(BaseModel):
    video_id: int
    models: list[str] = Field(..., min_length=1)
    configs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    options: JobOptionsIn = Field(default_factory=JobOptionsIn)


class PlanStepOut(BaseModel):
    model_id: str
    name: str
    kind: str
    auto_added: bool
    depends_on: list[str]
    configuration: dict[str, Any]


class PlanOut(BaseModel):
    steps: list[PlanStepOut]
    auto_added: list[str]
    frames_to_process: int
    estimated_seconds: float
    estimate_breakdown: dict[str, float]
    estimate_measured: bool
    warnings: list[str]


class JobModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    name: str | None = None
    model_version: str
    weights_sha256: dict[str, str]
    configuration: dict[str, Any]
    position: int
    auto_added: bool
    execution_status: str
    execution_time: float | None = None
    error_message: str | None = None


class JobOut(BaseModel):
    id: int
    video_id: int
    video_filename: str | None = None
    status: str
    progress: float
    current_stage: str | None = None
    progress_detail: dict[str, Any]
    options: dict[str, Any]
    summary: dict[str, Any]
    device: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    has_annotated_video: bool = False
    queue_position: int | None = None
    models: list[JobModelOut]


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int
    pages: int


class ProgressOut(BaseModel):
    job_id: int
    status: str
    progress: float
    current_stage: str | None = None
    detail: dict[str, Any]
    error_message: str | None = None
    queue_position: int | None = None
    models: list[dict[str, Any]]


# ----------------------------------------------------------------- results
class ActivitySegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    track_id: int
    start_time: float
    end_time: float
    label: str
    confidence: float
    method: str


class PersonOut(BaseModel):
    track_id: int
    first_seen: float
    last_seen: float
    duration: float
    frame_count: int
    avg_confidence: float
    trajectory: list[list[float]]
    dominant_activity: dict[str, str | None] = Field(default_factory=dict)  # model_id -> label
    activities: list[ActivitySegmentOut] = Field(default_factory=list)


class ActivityModelSummary(BaseModel):
    model_id: str
    name: str
    distribution_seconds: dict[str, float]
    average_confidence: float | None
    segment_count: int


class ResultsOut(BaseModel):
    job: JobOut
    video: VideoOut
    unique_people: int | None
    total_detections: int
    average_people_per_frame: float | None
    max_people_in_frame: int | None
    frames_processed: int
    processing_seconds: float | None
    processing_fps: float | None
    posture_distribution: dict[str, int]
    activity_models: list[ActivityModelSummary]
    people_over_time: list[list[float]]   # [t, count]
    coord_width: int | None
    coord_height: int | None
    available_overlays: list[str]


class FramePersonOut(BaseModel):
    box: list[float]
    conf: float
    track_id: int | None = None
    keypoints: list[list[float]] | None = None
    posture: dict[str, Any] | None = None


class FrameOut(BaseModel):
    f: int
    t: float
    persons: list[FramePersonOut]


class FramesOut(BaseModel):
    start: float
    end: float
    coord_width: int | None
    coord_height: int | None
    fps: float | None
    frame_interval: int
    frames: list[FrameOut]


class ActivitiesOut(BaseModel):
    segments: list[ActivitySegmentOut]
    models: list[ActivityModelSummary]


# --------------------------------------------------------------- dashboard
class DashboardOut(BaseModel):
    total_videos: int
    videos_by_status: dict[str, int]
    total_jobs: int
    jobs_by_status: dict[str, int]
    total_models: int
    available_models: int
    people_tracked: int
    total_processing_seconds: float
    recent_jobs: list[JobOut]
    recent_videos: list[VideoOut]
    worker: dict[str, Any]
    activity_totals: dict[str, float]


class SystemInfoOut(BaseModel):
    app_name: str
    version: str
    device: str
    cuda_available: bool
    cuda_device: str | None
    torch_threads: int
    max_upload_size_mb: int
    max_video_duration_seconds: float
    max_inference_height: int
    max_loaded_models: int
    allowed_extensions: list[str]
    results_retention_days: int
    allow_model_download: bool
    worker: dict[str, Any]
    disk_free_gb: float
