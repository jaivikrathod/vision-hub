"""Draws stored results onto frames for the annotated MP4 export.

Works purely from merged per-frame data (``person_detections``,
``person_keypoints``, ``posture_labels``, ``person_tracks``) plus activity
segments, so it never re-runs a model.
"""

from __future__ import annotations

import bisect
import colorsys
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from app.vision import data_types as dt


@dataclass
class OverlayOptions:
    show_boxes: bool = True
    show_ids: bool = True
    show_skeleton: bool = True
    show_posture: bool = True
    show_activity: bool = True
    show_confidence: bool = False
    keypoint_threshold: float = 0.35


def track_color(track_id: int | None) -> tuple[int, int, int]:
    """Stable, distinct BGR colour per track (golden-ratio hue spacing)."""
    if track_id is None:
        return (0, 200, 0)
    hue = (track_id * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
    return int(b * 255), int(g * 255), int(r * 255)


class ActivityLookup:
    """Find the activity label(s) of a track at a timestamp."""

    def __init__(self, segments_by_model: dict[str, list[dict]]) -> None:
        self._index: dict[tuple[str, int], tuple[list[float], list[dict]]] = {}
        self.model_ids = list(segments_by_model)
        for model_id, segments in segments_by_model.items():
            per_track: dict[int, list[dict]] = {}
            for s in segments:
                per_track.setdefault(int(s["track_id"]), []).append(s)
            for tid, segs in per_track.items():
                segs.sort(key=lambda s: s["start"])
                self._index[(model_id, tid)] = ([s["start"] for s in segs], segs)

    def at(self, track_id: int, t: float) -> list[tuple[str, dict]]:
        out = []
        for model_id in self.model_ids:
            entry = self._index.get((model_id, track_id))
            if not entry:
                continue
            starts, segs = entry
            i = bisect.bisect_right(starts, t) - 1
            if i >= 0 and segs[i]["start"] <= t <= segs[i]["end"]:
                out.append((model_id, segs[i]))
        return out


def merge_persons(data: dict[str, Any], valid_tracks: set[int] | None = None) -> list[dict]:
    """Combine aligned per-frame lists into one record per detected person."""
    dets = data.get(dt.PERSON_DETECTIONS) or []
    kps = data.get(dt.PERSON_KEYPOINTS) or []
    postures = data.get(dt.POSTURE_LABELS) or []
    tracks = {t["det"]: t["id"] for t in data.get(dt.PERSON_TRACKS) or []}
    has_tracking = dt.PERSON_TRACKS in data
    persons = []
    for i, det in enumerate(dets):
        tid = tracks.get(i)
        if has_tracking and valid_tracks is not None and tid is not None and tid not in valid_tracks:
            tid = None
        persons.append({
            "box": det["box"], "conf": det["conf"], "track_id": tid,
            "keypoints": kps[i] if i < len(kps) else None,
            "posture": postures[i] if i < len(postures) else None,
        })
    return persons


class FrameAnnotator:
    def __init__(self, options: OverlayOptions, width: int, height: int,
                 activities: ActivityLookup | None = None) -> None:
        self.opt = options
        self.activities = activities
        scale = max(width, height) / 1280.0
        self.thickness = max(2, round(2 * scale))
        self.font_scale = max(0.45, 0.55 * scale)
        self.font_thickness = max(1, round(1.4 * scale))
        self.pad = max(3, round(4 * scale))
        self.radius = max(2, round(3 * scale))
        self.font = cv2.FONT_HERSHEY_SIMPLEX

    def _labels(self, p: dict, t: float) -> list[str]:
        lines = []
        head = []
        if self.opt.show_ids and p["track_id"] is not None:
            head.append(f"#{p['track_id']}")
        if self.opt.show_confidence:
            head.append(f"{p['conf']:.2f}")
        if head:
            lines.append(" ".join(head))
        if self.opt.show_posture and p["posture"] and p["posture"]["label"] != "unknown":
            lines.append(f"Posture: {p['posture']['label']}")
        if self.opt.show_activity and self.activities and p["track_id"] is not None:
            both = len(self.activities.model_ids) > 1
            for model_id, seg in self.activities.at(p["track_id"], t):
                tag = ("X-CLIP" if model_id == "activity_xclip" else "Pose-based") if both else "Activity"
                conf = f" {seg['confidence']:.2f}" if self.opt.show_confidence else ""
                lines.append(f"{tag}: {seg['label']}{conf}")
        return lines

    def draw(self, frame: np.ndarray, persons: list[dict], t: float) -> np.ndarray:
        """Draw in place and return the frame."""
        h, w = frame.shape[:2]
        for p in persons:
            color = track_color(p["track_id"])
            x1, y1, x2, y2 = (int(v) for v in p["box"])
            x1, x2 = max(0, min(w - 1, x1)), max(0, min(w - 1, x2))
            y1, y2 = max(0, min(h - 1, y1)), max(0, min(h - 1, y2))
            if self.opt.show_boxes:
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, self.thickness, cv2.LINE_AA)
            if self.opt.show_skeleton and p["keypoints"]:
                self._skeleton(frame, p["keypoints"], color)
            self._text_block(frame, self._labels(p, t), x1, y1, color)
        return frame

    def _skeleton(self, frame: np.ndarray, kps: list, color: tuple[int, int, int]) -> None:
        thr = self.opt.keypoint_threshold
        for a, b in dt.SKELETON:
            if kps[a][2] >= thr and kps[b][2] >= thr:
                cv2.line(frame, (int(kps[a][0]), int(kps[a][1])), (int(kps[b][0]), int(kps[b][1])),
                         color, max(1, self.thickness - 1), cv2.LINE_AA)
        for x, y, c in kps:
            if c >= thr:
                cv2.circle(frame, (int(x), int(y)), self.radius, (255, 255, 255), -1, cv2.LINE_AA)

    def _text_block(self, frame: np.ndarray, lines: list[str], x1: int, y1: int,
                    color: tuple[int, int, int]) -> None:
        if not lines:
            return
        h, w = frame.shape[:2]
        sizes = [cv2.getTextSize(s, self.font, self.font_scale, self.font_thickness) for s in lines]
        line_h = max(th + bl for (_, th), bl in sizes) + self.pad
        block_w = max(tw for (tw, _), _ in sizes) + 2 * self.pad
        block_h = line_h * len(lines) + self.pad
        top = y1 - block_h if y1 - block_h >= 0 else y1
        left = min(x1, max(0, w - block_w))
        cv2.rectangle(frame, (left, top), (left + block_w, top + block_h), color, -1)
        for i, text in enumerate(lines):
            (_, th), _ = sizes[i]
            y = top + self.pad + th + i * line_h
            cv2.putText(frame, text, (left + self.pad, y), self.font, self.font_scale, (0, 0, 0),
                        self.font_thickness, cv2.LINE_AA)
