"""Fake model plugins for tests (deterministic, no weights, no downloads)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.vision import data_types as dt
from app.vision.base_model import BaseVisionModel, FrameData, JobContext, ModelSpec, ResultsReader


def walking_person(t: float, height: float = 160.0, x0: float = 40.0, speed: float = 80.0) -> tuple[list, list]:
    """Box and COCO keypoints of an upright person moving right at ``speed`` px/s, alternating feet."""
    import math

    x = x0 + speed * t
    top = 40.0
    box = [x - 25, top, x + 25, top + height]
    kps = [[x, top + 10, 0.9]] * 5  # head points
    sh_y, hip_y, knee_y, ank_y = top + 0.25 * height, top + 0.55 * height, top + 0.78 * height, top + height
    swing = 18 * math.sin(2 * math.pi * 1.0 * t) if speed else 0.0  # 1 Hz stride -> 2 foot swaps/s
    kps += [[x - 12, sh_y, 0.9], [x + 12, sh_y, 0.9],         # shoulders
            [x - 15, sh_y + 30, 0.9], [x + 15, sh_y + 30, 0.9],  # elbows
            [x - 16, sh_y + 55, 0.9], [x + 16, sh_y + 55, 0.9],  # wrists
            [x - 8, hip_y, 0.9], [x + 8, hip_y, 0.9],          # hips
            [x - 8 + swing / 2, knee_y, 0.9], [x + 8 - swing / 2, knee_y, 0.9],  # knees
            [x - 8 + swing, ank_y, 0.9], [x + 8 - swing, ank_y, 0.9]]  # ankles
    return box, kps


class FakePoseConfig(BaseModel):
    speed: float = Field(80.0, ge=0, le=1000)
    fail_on_frame: int = Field(-1, description="Raise on this frame index (testing failure handling)")


class FakePoseModel(BaseVisionModel):
    """Emits one walking person per frame (or none after 2.5 s), with a fixed posture."""

    spec = ModelSpec(
        model_id="fake_pose", name="Fake Pose", category="test", version="0.0.1",
        description="Deterministic fake pose model for tests", license="MIT", kind="frame",
        produces=[dt.PERSON_DETECTIONS, dt.PERSON_KEYPOINTS, dt.POSTURE_LABELS],
        config_schema=FakePoseConfig, neural=False, default_seconds_per_frame=0.0001,
        priority=-10,  # never auto-added in place of the real pose model
    )

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        if frame.index == ctx.config.fail_on_frame:
            raise RuntimeError("boom")
        if frame.timestamp > 2.5:
            return {dt.PERSON_DETECTIONS: [], dt.PERSON_KEYPOINTS: [], dt.POSTURE_LABELS: []}
        box, kps = walking_person(frame.timestamp, speed=ctx.config.speed)
        return {dt.PERSON_DETECTIONS: [{"box": box, "conf": 0.9}], dt.PERSON_KEYPOINTS: [kps],
                dt.POSTURE_LABELS: [{"label": "standing", "conf": 0.9}]}


class CountConfig(BaseModel):
    pass


class FakeCounterModel(BaseVisionModel):
    """A post model that counts tracked frames per track (tests post-model plumbing)."""

    spec = ModelSpec(
        model_id="fake_counter", name="Fake Counter", category="test", version="0.0.1",
        description="Counts frames per track", license="MIT", kind="post",
        requires=[dt.PERSON_TRACKS], produces=["fake_counts"], config_schema=CountConfig, neural=False,
    )

    def process_results(self, reader: ResultsReader, ctx: JobContext) -> dict[str, Any]:
        counts: dict[int, int] = {}
        for _f, _t, data in reader.iter_frames():
            for tr in data.get(dt.PERSON_TRACKS) or []:
                counts[tr["id"]] = counts.get(tr["id"], 0) + 1
        return {"fake_counts": counts}


class FakeBrightnessModel(BaseVisionModel):
    """An independent frame model (no requirements) used to test partial failures."""

    spec = ModelSpec(
        model_id="fake_brightness", name="Fake Brightness", category="test", version="0.0.1",
        description="Mean pixel value per frame", license="MIT", kind="frame",
        produces=["brightness"], config_schema=CountConfig, neural=False,
    )

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        return {"brightness": float(frame.image.mean())}


FAKES = [FakePoseModel, FakeCounterModel, FakeBrightnessModel]
