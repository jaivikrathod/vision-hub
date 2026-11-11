"""Pose-based temporal activity recognition (fast, rule-based, CPU friendly)."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from app.vision import data_types as dt
from app.vision.activity_utils import UNCERTAIN, pick_label, smooth_labels, window_starts, windows_to_segments
from app.vision.base_model import BaseVisionModel, JobContext, ModelSpec, ResultsReader
from app.vision.plugins.activity_pose_temporal.features import (
    ACTIVITIES,
    ActivityThresholds,
    TrackSeries,
    score_window,
    window_features,
)

METHOD = "pose-temporal"


class PoseActivityConfig(BaseModel):
    window_seconds: float = Field(1.5, ge=0.5, le=5.0, description="Length of each analysed clip (seconds)")
    stride_seconds: float = Field(0.5, ge=0.1, le=5.0, description="Step between clips (seconds)")
    min_frames: int = Field(4, ge=2, le=60, description="Minimum processed frames of a person inside a clip")
    confidence_threshold: float = Field(
        0.45, ge=0.05, le=0.95, description="Below this the activity is reported as 'uncertain'")
    smoothing_windows: int = Field(3, ge=1, le=9, description="Majority filter over neighbouring clips (odd number)")
    keypoint_confidence: float = Field(0.35, ge=0.05, le=0.95, description="Keypoints below this are ignored")
    enable_falling: bool = Field(True, description="Detect falls with a heuristic (fast hip drop ending lying down)")
    thresholds: ActivityThresholds = Field(default_factory=ActivityThresholds)


class PoseActivityModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="activity_pose_temporal",
        name="Activity Recognition (Pose-based)",
        category="activity",
        version="1.0.0",
        description=(
            "Recognises what each tracked person is doing from how their body keypoints move over short "
            "clips (default 1.5 s): walking, running, jumping, standing, sitting, lying down, bending, and "
            "falling (heuristic). Fast on CPU because it adds no neural network."
        ),
        license="MIT (project code)",
        kind="post",
        requires=[dt.PERSON_TRACKS, dt.PERSON_KEYPOINTS, dt.POSTURE_LABELS],
        produces=[dt.ACTIVITY_SEGMENTS, dt.ACTIVITY_WINDOWS],
        weights=[],
        config_schema=PoseActivityConfig,
        neural=False,
        default_seconds_per_frame=0.001,
        cost_hint="Negligible; runs over stored keypoints after the video pass",
        labels=[*ACTIVITIES, UNCERTAIN],
        method=(
            "Per track, sliding windows over time; scores from body-height-normalised hip velocity, size "
            "change, ankle alternation, foot rise, hip drop and the posture mix; smoothed and merged into segments"
        ),
        limitations=[
            "Motion straight towards or away from the camera is estimated from size change and is less precise.",
            "Running vs walking uses speed in body heights per second; very slow running or fast walking can swap.",
            "Falling is a heuristic (fast hip drop ending lying down), not a trained fall detector.",
            "Needs the person's hips/ankles to be visible; otherwise the result is 'uncertain'.",
        ],
    )

    def process_results(self, reader: ResultsReader, ctx: JobContext) -> dict[str, Any]:
        cfg: PoseActivityConfig = ctx.config
        valid = {s["track_id"] for s in ctx.upstream_final.get(dt.TRACK_SUMMARIES, [])} or None

        # Collect each track's time series from stored per-frame results.
        series: dict[int, dict[str, list]] = {}
        total = max(1, reader.frame_count())
        for i, (_f, t, data) in enumerate(reader.iter_frames()):
            if i % 200 == 0:
                ctx.report(0.5 * i / total, "Collecting keypoint sequences")
            dets = data.get(dt.PERSON_DETECTIONS) or []
            kps = data.get(dt.PERSON_KEYPOINTS) or []
            postures = data.get(dt.POSTURE_LABELS) or []
            for tr in data.get(dt.PERSON_TRACKS) or []:
                tid, di = tr["id"], tr["det"]
                if (valid is not None and tid not in valid) or di >= len(dets) or di >= len(kps):
                    continue
                s = series.setdefault(tid, {"t": [], "box": [], "kps": [], "posture": []})
                s["t"].append(t)
                s["box"].append(dets[di]["box"])
                s["kps"].append(kps[di])
                s["posture"].append(postures[di]["label"] if di < len(postures) else "unknown")

        windows_all: list[dict] = []
        segments_all: list[dict] = []
        for n, (tid, s) in enumerate(sorted(series.items())):
            ctx.report(0.5 + 0.5 * n / max(1, len(series)), "Scoring activity windows")
            t = np.asarray(s["t"], dtype=np.float64)
            box = np.asarray(s["box"], dtype=np.float64)
            kps = np.asarray(s["kps"], dtype=np.float64)
            windows = []
            for start in window_starts(float(t[0]), float(t[-1]), cfg.window_seconds, cfg.stride_seconds):
                end = start + cfg.window_seconds
                idx = np.nonzero((t >= start - 1e-6) & (t <= end + 1e-6))[0]
                if len(idx) < cfg.min_frames:
                    continue
                win = TrackSeries(t[idx], box[idx], kps[idx], [s["posture"][i] for i in idx])
                feats = window_features(win, cfg.keypoint_confidence)
                scores = score_window(feats, cfg.thresholds, cfg.enable_falling)
                label, conf = pick_label(scores, cfg.confidence_threshold)
                windows.append({
                    "track_id": tid, "start": round(float(t[idx[0]]), 3), "end": round(float(t[idx[-1]]), 3),
                    "scores": scores, "label": label, "confidence": round(conf, 3),
                    "features": {k: round(v, 4) for k, v in feats.items()},
                })
            if not windows:
                continue
            k = cfg.smoothing_windows if cfg.smoothing_windows % 2 else cfg.smoothing_windows + 1
            labels = smooth_labels(windows, k)
            segments_all.extend(windows_to_segments(windows, labels, cfg.stride_seconds, METHOD))
            windows_all.extend(windows)
        return {dt.ACTIVITY_SEGMENTS: segments_all, dt.ACTIVITY_WINDOWS: windows_all}


PLUGIN = PoseActivityModel
