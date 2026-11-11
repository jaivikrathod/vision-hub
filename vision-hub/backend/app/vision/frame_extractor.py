"""Streaming frame extraction with sampling, timestamps and downscaling.

Frames are decoded one at a time (the video is never loaded into RAM).
``FrameExtractor`` yields every decoded frame and marks which ones are sampled
(every ``frame_interval``-th), so callers can process sampled frames while
still seeing all frames (e.g. to render a full-length annotated video).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.exceptions import CorruptedVideoError

logger = logging.getLogger(__name__)


def processing_size(width: int, height: int, max_height: int) -> tuple[int, int]:
    """Frame size used for inference: downscale (keeping aspect) when taller than ``max_height``."""
    if max_height and height > max_height:
        scale = max_height / height
        w = int(round(width * scale / 2) * 2)
        return max(2, w), max_height - (max_height % 2)
    return width, height


@dataclass
class ExtractedFrame:
    index: int
    timestamp: float
    image: np.ndarray
    sampled: bool


class FrameExtractor:
    def __init__(self, path: Path, frame_interval: int = 1, max_height: int = 0,
                 fps_hint: float | None = None) -> None:
        self.path = path
        self.frame_interval = max(1, int(frame_interval))
        self.max_height = max_height
        self.fps_hint = fps_hint
        self.frames_read = 0

    def open(self) -> tuple[cv2.VideoCapture, float, int, int, int]:
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise CorruptedVideoError("The video could not be opened for processing.")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not np.isfinite(fps) or fps <= 0 or fps > 1000:
            fps = self.fps_hint or 25.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return cap, float(fps), width, height, total

    def frames(self) -> Iterator[ExtractedFrame]:
        """Yield frames in order. Timestamps are ``index / fps`` (deterministic and reproducible)."""
        cap, fps, width, height, total = self.open()
        target = processing_size(width, height, self.max_height) if width and height else None
        index = 0
        try:
            while True:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                if target and (frame.shape[1], frame.shape[0]) != target:
                    frame = cv2.resize(frame, target, interpolation=cv2.INTER_AREA)
                self.frames_read += 1
                yield ExtractedFrame(index=index, timestamp=round(index / fps, 4),
                                     image=frame, sampled=index % self.frame_interval == 0)
                index += 1
        finally:
            cap.release()
        if total and index < total * 0.9:
            logger.warning("%s: decoded %d of %d reported frames (stream may be truncated)",
                           self.path.name, index, total)
