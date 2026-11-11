"""Multi-person tracking with ByteTrack via the Ultralytics tracking API."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.config import settings


@dataclass(slots=True)
class PersonDetection:
    track_id: int
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


class PersonTracker:
    """Wraps ``model.track(..., persist=True)`` for one video.

    Track IDs are video-local ByteTrack identifiers. They survive short
    detection gaps (``track_buffer`` frames) but are not real-world identities
    and are not guaranteed after long occlusions.
    """

    def __init__(
        self,
        model,
        *,
        confidence: float,
        device: str,
        tracker_config: str | None = None,
        image_size: int | None = None,
    ) -> None:
        self.model = model
        self.confidence = confidence
        self.device = device
        self.tracker_config = tracker_config or settings.tracker_config
        self.image_size = image_size or settings.inference_image_size

    def update(self, frame: np.ndarray) -> list[PersonDetection]:
        results = self.model.track(
            frame,
            persist=True,
            classes=[settings.person_class_id],
            tracker=self.tracker_config,
            conf=self.confidence,
            device=self.device,
            imgsz=self.image_size,
            verbose=False,
        )
        if not results:
            return []
        boxes = results[0].boxes
        if boxes is None or boxes.id is None or len(boxes) == 0:
            # Detections without an assigned track (not yet confirmed) are ignored.
            return []
        xyxy = boxes.xyxy.cpu().numpy()
        ids = boxes.id.int().cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        return [
            PersonDetection(int(tid), float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(c))
            for b, tid, c in zip(xyxy, ids, confs)
        ]
