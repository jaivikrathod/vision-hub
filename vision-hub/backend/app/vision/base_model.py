"""The common interface every vision model plugin implements.

A plugin is a :class:`BaseVisionModel` subclass with a :class:`ModelSpec`.
The executor is the only caller. Plugins:

* never read the video file themselves - they receive frames or stored results;
* never write to the database - they return JSON-serialisable outputs;
* keep per-job state in ``ctx.state`` (one model instance is shared across jobs
  so its weights are loaded only once).

Three kinds of model are supported:

``frame``  ``process_frame`` is called for every sampled frame in the single
           decode pass; outputs are stored per frame.
``clip``   also fed every sampled frame (so it can buffer person crops), but
           produces windowed, job-level outputs, returned from ``finish``.
``post``   runs once after the decode pass over the stored results of its
           upstream models (``process_results``).
"""

from __future__ import annotations

import logging
from abc import ABC
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

ModelKind = Literal["frame", "clip", "post"]


class WeightInfo(BaseModel):
    """One weight artifact a model needs."""

    name: str                                   # file name or local folder name in model_weights/
    source: str                                 # URL or Hugging Face repo id
    kind: Literal["file", "hf_snapshot"] = "file"
    size_mb: float | None = None                # approximate download size
    license: str | None = None


class ModelSpec(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    model_id: str
    name: str
    category: str
    version: str
    description: str
    license: str
    kind: ModelKind
    requires: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    weights: list[WeightInfo] = Field(default_factory=list)
    config_schema: type[BaseModel]
    # Whether the model holds neural-network weights in memory (counts towards MAX_LOADED_MODELS).
    neural: bool = True
    # When several installed models can provide a missing input, the planner auto-adds the
    # one with the highest priority.
    priority: int = 0
    # Fallback runtime estimate until a real measurement exists on this machine.
    default_seconds_per_frame: float = 0.05
    cost_hint: str = ""
    input_types: list[str] = Field(default_factory=lambda: ["video"])
    labels: list[str] = Field(default_factory=list)
    method: str = ""
    limitations: list[str] = Field(default_factory=list)

    def public_dict(self) -> dict:
        data = self.model_dump(exclude={"config_schema"})
        data["config_schema"] = self.config_schema.model_json_schema()
        data["default_config"] = self.config_schema().model_dump(mode="json")
        return data


@dataclass
class VideoInfo:
    fps: float
    width: int                 # processing-frame size (after any downscaling)
    height: int
    source_width: int
    source_height: int
    total_frames: int
    duration: float
    frame_interval: int        # process every Nth frame

    @property
    def processed_fps(self) -> float:
        return self.fps / max(1, self.frame_interval)

    @property
    def scale(self) -> float:
        return self.width / self.source_width if self.source_width else 1.0


@dataclass
class FrameData:
    index: int                 # frame number in the source video
    timestamp: float           # seconds
    image: np.ndarray          # BGR, processing size


@dataclass
class JobContext:
    """Per-job, per-model context handed to plugin methods."""

    job_id: int
    model_id: str
    config: Any                                  # instance of spec.config_schema
    video: VideoInfo
    device: str
    state: dict = field(default_factory=dict)    # plugin's private per-job state
    # Job-level outputs of models that already finished, by data type.
    upstream_final: dict[str, Any] = field(default_factory=dict)
    is_cancelled: Callable[[], bool] = lambda: False
    report: Callable[[float, str | None], None] = lambda fraction, message=None: None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("vision.plugin"))


class ResultsReader(ABC):
    """Read access to stored per-frame results, for ``post`` models."""

    def iter_frames(self) -> Iterator[tuple[int, float, dict[str, Any]]]:  # pragma: no cover - interface
        """Yield ``(frame_index, timestamp, {data_type: value})`` in time order."""
        raise NotImplementedError

    def frame_count(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError


class BaseVisionModel(ABC):
    spec: ModelSpec

    def __init__(self) -> None:
        self._loaded = False
        self.device = "cpu"

    # ---------------------------------------------------------------- lifecycle
    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self, device: str) -> None:
        """Load weights onto ``device``. Rule-based models need not override."""
        self.device = device
        self._loaded = True

    def unload(self) -> None:
        self._loaded = False

    @classmethod
    def advice(cls, config: Any, video: dict[str, Any]) -> list[str]:
        """Optional tips shown before a job starts, e.g. a better setting for this video.

        ``video`` has ``width``, ``height``, ``fps``, ``duration`` and ``total_frames``.
        """
        return []

    @classmethod
    def relative_cost(cls, config: Any) -> float:
        """Inference cost of ``config`` relative to the default configuration (1.0).

        Benchmarks are stored normalised to the defaults and estimates are scaled by
        this factor, so e.g. a larger detection size gives a longer estimate.
        """
        return 1.0

    def weight_hashes(self, config: Any) -> dict[str, str]:
        """SHA-256 of the weights used with ``config``, recorded with every job for reproducibility."""
        return {}

    # -------------------------------------------------------------- per job
    def start_job(self, ctx: JobContext) -> None:
        """Initialise ``ctx.state`` before the first frame."""

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        """``frame``/``clip`` models: return ``{data_type: value}`` for this frame.

        ``upstream`` holds this frame's outputs from models earlier in the pipeline,
        e.g. ``upstream["person_detections"]``.
        """
        return {}

    def finish(self, ctx: JobContext) -> dict[str, Any]:
        """``frame``/``clip`` models: return job-level outputs after the last frame."""
        return {}

    def process_results(self, reader: ResultsReader, ctx: JobContext) -> dict[str, Any]:
        """``post`` models: compute job-level outputs from stored upstream results."""
        return {}
