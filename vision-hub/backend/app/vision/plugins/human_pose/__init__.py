"""Human Detection & Pose Estimation (YOLO11-pose) with rule-based posture."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.exceptions import ModelLoadError
from app.vision import data_types as dt
from app.vision import weights
from app.vision.base_model import BaseVisionModel, FrameData, JobContext, ModelSpec, WeightInfo
from app.vision.plugins.human_pose.posture import POSTURES, UNKNOWN, PostureThresholds, classify_posture

_WEIGHTS = {
    "yolo11n-pose.pt": WeightInfo(
        name="yolo11n-pose.pt", size_mb=6,
        source="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt",
        license="AGPL-3.0",
    ),
    "yolo11s-pose.pt": WeightInfo(
        name="yolo11s-pose.pt", size_mb=20,
        source="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11s-pose.pt",
        license="AGPL-3.0",
    ),
}


class HumanPoseConfig(BaseModel):
    weights: Literal["yolo11n-pose.pt", "yolo11s-pose.pt"] = Field(
        "yolo11n-pose.pt", description="Nano is fastest on CPU; Small is more accurate but ~2.5x slower")
    confidence: float = Field(0.40, ge=0.05, le=0.95, description="Minimum person detection confidence")
    image_size: Literal[640, 960, 1280] = Field(
        960, description=(
            "Detection resolution (longer side, pixels). 640: fastest, for people who fill a good part of "
            "the frame. 960: balanced, also finds small or distant people. 1280: best for crowds and "
            "surveillance footage, about 2x slower than 960"))
    keypoint_confidence: float = Field(0.35, ge=0.05, le=0.95,
                                       description="Keypoints below this confidence are ignored")
    classify_posture: bool = Field(True, description="Estimate posture from keypoint geometry")
    posture: PostureThresholds = Field(default_factory=PostureThresholds)


class HumanPoseModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="human_pose",
        name="Human Detection & Pose Estimation",
        category="pose",
        # 1.1.0: default detection size 640 -> 960 (small/distant people were missed at 640).
        version="1.1.0",
        description=(
            "Detects people with YOLO11-pose and estimates 17 body keypoints (head, shoulders, elbows, "
            "wrists, hips, knees, ankles) per person, draws the skeleton, and classifies posture from "
            "keypoint geometry."
        ),
        license="AGPL-3.0 (Ultralytics YOLO11)",
        kind="frame",
        requires=[],
        produces=[dt.PERSON_DETECTIONS, dt.PERSON_KEYPOINTS, dt.POSTURE_LABELS],
        weights=list(_WEIGHTS.values()),
        config_schema=HumanPoseConfig,
        neural=True,
        default_seconds_per_frame=0.14,
        cost_hint="~7 frames/s with YOLO11n-pose at 960 px on a 12-core laptop CPU (~13 at 640, ~4 at 1280)",
        labels=[*POSTURES, UNKNOWN],
        method="YOLO11-pose (COCO-17 keypoints) + rule-based posture from torso angle, knee angle and thigh drop",
        limitations=[
            "Posture rules depend on camera angle; seated people facing the camera or top-down views can be misread.",
            "Returns 'unknown' when hips, shoulders or legs are not visible instead of guessing.",
            "Small or distant people are missed at 640 px; use 960 (default) or 1280 for wide shots and crowds.",
            "Heavily occluded people may be missed or get incomplete skeletons.",
        ],
    )

    @classmethod
    def advice(cls, config: HumanPoseConfig, video: dict) -> list[str]:
        longest = max(video.get("width") or 0, video.get("height") or 0)
        if config.image_size < 1280 and 0 < longest <= 1024:
            # Measured on a 768x576 surveillance clip: 1 person found at 960 px vs 5 at 1280 px.
            return [f"This is a low-resolution video ({video['width']}×{video['height']}), so people are often "
                    "small. If people are missed, set the pose model's detection resolution to 1280 "
                    "(slower, but finds far more small people)."]
        return []

    @classmethod
    def relative_cost(cls, config: HumanPoseConfig) -> float:
        # Convolutional cost grows with pixel count; the Small model costs ~2.5x the Nano one.
        return (config.image_size / 960) ** 2 * (2.5 if config.weights == "yolo11s-pose.pt" else 1.0)

    def __init__(self) -> None:
        super().__init__()
        self._yolo: dict[str, Any] = {}

    def load(self, device: str) -> None:
        # Weights are loaded per variant in start_job (the variant is a job setting).
        weights.configure_ultralytics()
        super().load(device)

    def unload(self) -> None:
        self._yolo.clear()
        super().unload()

    def _model(self, name: str):
        if name not in self._yolo:
            path = weights.ensure_weights(_WEIGHTS[name])
            try:
                from ultralytics import YOLO

                self._yolo[name] = YOLO(str(path), task="pose")
            except Exception as exc:
                raise ModelLoadError(f"Failed to load {name}: {exc}") from exc
        return self._yolo[name]

    def weight_hashes(self, config: HumanPoseConfig) -> dict[str, str]:
        digest = weights.sha256_of(_WEIGHTS[config.weights])
        return {config.weights: digest} if digest else {}

    def start_job(self, ctx: JobContext) -> None:
        ctx.state["model"] = self._model(ctx.config.weights)

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        cfg: HumanPoseConfig = ctx.config
        results = ctx.state["model"].predict(
            frame.image, conf=cfg.confidence, imgsz=cfg.image_size, device=self.device,
            verbose=False, classes=[0],
        )
        dets, kps_out, postures = [], [], []
        if results:
            r = results[0]
            boxes = r.boxes
            kps = r.keypoints.data.cpu().numpy() if r.keypoints is not None else None
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.cpu().numpy()
                conf = boxes.conf.cpu().numpy()
                for i in range(len(xyxy)):
                    box = [round(float(v), 1) for v in xyxy[i]]
                    dets.append({"box": box, "conf": round(float(conf[i]), 4)})
                    person_kps = ([[round(float(x), 1), round(float(y), 1), round(float(c), 3)]
                                   for x, y, c in kps[i]] if kps is not None and i < len(kps) else
                                  [[0.0, 0.0, 0.0]] * 17)
                    kps_out.append(person_kps)
                    if cfg.classify_posture:
                        postures.append(classify_posture(person_kps, box, cfg.keypoint_confidence,
                                                         cfg.posture).as_dict())
                    else:
                        postures.append({"label": UNKNOWN, "conf": 0.0})
        return {dt.PERSON_DETECTIONS: dets, dt.PERSON_KEYPOINTS: kps_out, dt.POSTURE_LABELS: postures}


PLUGIN = HumanPoseModel
