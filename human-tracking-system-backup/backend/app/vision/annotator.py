"""Frame annotation: green bounding boxes with tracking-ID labels."""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import settings
from app.services.tracking_service import PersonDetection


@dataclass
class VisualizationSettings:
    show_boxes: bool = True
    show_ids: bool = True
    show_confidence: bool = False
    color: tuple[int, int, int] = field(default_factory=lambda: tuple(settings.box_color_bgr))
    text_color: tuple[int, int, int] = (0, 0, 0)


class FrameAnnotator:
    def __init__(self, viz: VisualizationSettings, frame_width: int, frame_height: int) -> None:
        self.viz = viz
        scale = max(frame_width, frame_height) / 1280.0
        self.thickness = max(2, round(2 * scale))
        self.font_scale = max(0.5, 0.6 * scale)
        self.font_thickness = max(1, round(1.5 * scale))
        self.pad = max(3, round(4 * scale))
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def _label(self, det: PersonDetection) -> str | None:
        parts = []
        if self.viz.show_ids:
            parts.append(f"Person #{det.track_id}")
        if self.viz.show_confidence:
            parts.append(f"{det.confidence:.2f}")
        return "  ".join(parts) if parts else None

    def draw(self, frame: np.ndarray, detections: list[PersonDetection]) -> np.ndarray:
        """Draw in place (no frame copy) and return the frame."""
        h, w = frame.shape[:2]
        for det in detections:
            x1 = int(max(0, min(w - 1, det.x1)))
            y1 = int(max(0, min(h - 1, det.y1)))
            x2 = int(max(0, min(w - 1, det.x2)))
            y2 = int(max(0, min(h - 1, det.y2)))
            if self.viz.show_boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), self.viz.color, self.thickness, cv2.LINE_AA)
            label = self._label(det)
            if not label:
                continue
            (tw, th), baseline = cv2.getTextSize(label, self.font, self.font_scale, self.font_thickness)
            box_h = th + baseline + 2 * self.pad
            # Above the box when there is room, otherwise just inside its top edge.
            top = y1 - box_h if y1 - box_h >= 0 else y1
            left = min(x1, max(0, w - tw - 2 * self.pad))
            cv2.rectangle(frame, (left, top), (left + tw + 2 * self.pad, top + box_h), self.viz.color, -1)
            cv2.putText(
                frame, label, (left + self.pad, top + self.pad + th),
                self.font, self.font_scale, self.viz.text_color, self.font_thickness, cv2.LINE_AA,
            )
        return frame
