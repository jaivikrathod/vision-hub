"""Adapter around Ultralytics' ``BYTETracker`` for externally supplied detections.

``BYTETracker`` is an internal Ultralytics API (tested against 8.4.x, which is
pinned in requirements.txt). It expects a results-like object exposing ``conf``,
``cls`` and ``xywh`` (centre x, centre y, width, height) that supports boolean
indexing, and returns rows ``[x1, y1, x2, y2, track_id, score, cls, idx]``
where ``idx`` is the index of the matched input detection. That index is how
track IDs are joined back to keypoints and postures.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np


class _Detections:
    """Minimal stand-in for ``ultralytics.engine.results.Boxes`` (numpy-backed)."""

    def __init__(self, xyxy: np.ndarray, conf: np.ndarray) -> None:
        self.xyxy = xyxy.astype(np.float32).reshape(-1, 4)
        self.conf = conf.astype(np.float32).reshape(-1)
        self.cls = np.zeros(len(self.conf), dtype=np.float32)
        wh = self.xyxy[:, 2:4] - self.xyxy[:, 0:2]
        centre = self.xyxy[:, 0:2] + wh / 2
        self.xywh = np.concatenate([centre, wh], axis=1)

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, mask) -> _Detections:
        return _Detections(self.xyxy[mask], self.conf[mask])


@dataclass
class TrackerSettings:
    track_high_thresh: float = 0.25
    track_low_thresh: float = 0.1
    new_track_thresh: float = 0.25
    track_buffer_frames: int = 30
    match_thresh: float = 0.8
    fuse_score: bool = True


class ByteTrackAdapter:
    def __init__(self, settings: TrackerSettings) -> None:
        from ultralytics.trackers.byte_tracker import BYTETracker

        args = SimpleNamespace(
            tracker_type="bytetrack",
            track_high_thresh=settings.track_high_thresh,
            track_low_thresh=settings.track_low_thresh,
            new_track_thresh=settings.new_track_thresh,
            track_buffer=max(1, int(settings.track_buffer_frames)),
            match_thresh=settings.match_thresh,
            fuse_score=settings.fuse_score,
        )
        self._tracker = BYTETracker(args)

    def update(self, boxes_xyxy: list[list[float]], confidences: list[float]) -> list[tuple[int, int]]:
        """Return ``[(detection_index, track_id), ...]`` for confirmed tracks in this frame."""
        dets = _Detections(np.asarray(boxes_xyxy, dtype=np.float32).reshape(-1, 4),
                           np.asarray(confidences, dtype=np.float32))
        out = self._tracker.update(dets)
        if out is None or len(out) == 0:
            return []
        pairs = []
        seen: set[int] = set()
        for row in np.asarray(out):
            idx, tid = int(row[-1]), int(row[4])
            if 0 <= idx < len(dets) and idx not in seen:
                seen.add(idx)
                pairs.append((idx, tid))
        return pairs
