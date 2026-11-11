"""Human Tracking: ByteTrack over the person detections of an upstream model."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from app.vision import data_types as dt
from app.vision.base_model import BaseVisionModel, FrameData, JobContext, ModelSpec

MAX_TRAJECTORY_POINTS = 300


class HumanTrackingConfig(BaseModel):
    track_buffer_seconds: float = Field(
        1.5, ge=0.1, le=10, description="How long a lost person is remembered (handles short occlusions)")
    match_threshold: float = Field(0.8, ge=0.1, le=0.99, description="Association threshold (higher = stricter)")
    new_track_threshold: float = Field(
        0.25, ge=0.05, le=0.95, description="Minimum detection confidence to start a new track")
    min_track_seconds: float = Field(
        0.5, ge=0, le=10, description="Tracks visible for less than this are discarded as noise")


class HumanTrackingModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="human_tracking",
        name="Human Tracking",
        category="tracking",
        version="1.0.0",
        description=(
            "Keeps a consistent temporary ID for every person across frames with ByteTrack, and records "
            "first/last seen time and movement trajectory. Uses the person boxes of the pose model, so "
            "people are detected only once."
        ),
        license="MIT (ByteTrack algorithm); Ultralytics implementation AGPL-3.0",
        kind="frame",
        requires=[dt.PERSON_DETECTIONS],
        produces=[dt.PERSON_TRACKS, dt.TRACK_SUMMARIES],
        weights=[],
        config_schema=HumanTrackingConfig,
        neural=False,
        default_seconds_per_frame=0.002,
        cost_hint="Negligible (< 2 ms per frame); detection cost belongs to the pose model",
        method="ByteTrack: Kalman-filter motion prediction + two-stage IoU association",
        limitations=[
            "IDs are temporary: a person who leaves and re-enters usually gets a new ID.",
            "Large frame intervals make motion between processed frames bigger and IDs less stable.",
            "Long full occlusions longer than the track buffer create new IDs.",
        ],
    )

    def start_job(self, ctx: JobContext) -> None:
        from app.vision.plugins.human_tracking.bytetrack_adapter import ByteTrackAdapter, TrackerSettings

        cfg: HumanTrackingConfig = ctx.config
        # Time-based settings are converted using the *processed* frame rate.
        buffer_frames = math.ceil(cfg.track_buffer_seconds * ctx.video.processed_fps)
        ctx.state["tracker"] = ByteTrackAdapter(TrackerSettings(
            new_track_thresh=cfg.new_track_threshold, track_buffer_frames=buffer_frames,
            match_thresh=cfg.match_threshold,
        ))
        ctx.state["tracks"] = {}

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        dets = upstream.get(dt.PERSON_DETECTIONS) or []
        # Called on every processed frame, even without detections, so lost tracks age correctly.
        pairs = ctx.state["tracker"].update([d["box"] for d in dets], [d["conf"] for d in dets])
        tracks: dict[int, dict] = ctx.state["tracks"]
        for det_idx, tid in pairs:
            box, conf = dets[det_idx]["box"], dets[det_idx]["conf"]
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            st = tracks.get(tid)
            if st is None:
                st = tracks[tid] = {"first": frame.timestamp, "frames": 0, "conf_sum": 0.0, "traj": []}
            st["last"] = frame.timestamp
            st["frames"] += 1
            st["conf_sum"] += conf
            st["traj"].append([round(frame.timestamp, 3), round(cx, 1), round(cy, 1)])
        return {dt.PERSON_TRACKS: [{"det": i, "id": tid} for i, tid in pairs]}

    def finish(self, ctx: JobContext) -> dict[str, Any]:
        cfg: HumanTrackingConfig = ctx.config
        summaries = []
        for tid, st in sorted(ctx.state["tracks"].items()):
            visible_seconds = st["frames"] / ctx.video.processed_fps
            if visible_seconds < cfg.min_track_seconds:
                continue
            traj = st["traj"]
            if len(traj) > MAX_TRAJECTORY_POINTS:
                step = len(traj) / MAX_TRAJECTORY_POINTS
                traj = [traj[int(i * step)] for i in range(MAX_TRAJECTORY_POINTS)] + [traj[-1]]
            summaries.append({
                "track_id": tid, "first_seen": st["first"], "last_seen": st["last"],
                "frame_count": st["frames"], "avg_confidence": round(st["conf_sum"] / st["frames"], 4),
                "trajectory": traj,
            })
        return {dt.TRACK_SUMMARIES: summaries}


PLUGIN = HumanTrackingModel
