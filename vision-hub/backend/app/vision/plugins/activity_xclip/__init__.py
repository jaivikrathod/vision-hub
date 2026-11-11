"""Zero-shot activity recognition with X-CLIP on per-person video clips.

ByteTrack assigns IDs online, so during the single decode pass this model keeps
a small, capped buffer of square person crops per active track (8 crops spread
over ``clip_seconds``). When a buffer is full the clip is queued; queued clips
are scored in small batches against text prompts. Memory stays bounded:
``max_tracks × 8`` crops of 224×224 plus one batch.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, Field, field_validator

from app.core.exceptions import ModelLoadError
from app.vision import data_types as dt
from app.vision import weights
from app.vision.activity_utils import UNCERTAIN, pick_label, smooth_labels, windows_to_segments
from app.vision.base_model import BaseVisionModel, FrameData, JobContext, ModelSpec, WeightInfo

METHOD = "xclip-zero-shot"
FRAMES_PER_CLIP = 8          # xclip-base-patch32 was trained with 8 frames
CROP_SIZE = 224
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

WEIGHTS = WeightInfo(
    name="xclip-base-patch32", kind="hf_snapshot", source="microsoft/xclip-base-patch32",
    size_mb=790, license="MIT",
)


class ActivityPrompt(BaseModel):
    label: str = Field(..., min_length=1, max_length=40, description="Name shown in the UI")
    prompt: str = Field(..., min_length=3, max_length=120, description="Text sent to the model")


# "a video of a person …" scored the correct activity higher and more consistently than
# "a person …" in our tests on real footage (prompt wording matters for zero-shot models).
DEFAULT_PROMPTS = [
    ActivityPrompt(label="walking", prompt="a video of a person walking"),
    ActivityPrompt(label="running", prompt="a video of a person running"),
    ActivityPrompt(label="jumping", prompt="a video of a person jumping"),
    ActivityPrompt(label="standing", prompt="a video of a person standing still"),
    ActivityPrompt(label="sitting", prompt="a video of a person sitting"),
    ActivityPrompt(label="lying down", prompt="a video of a person lying down"),
    ActivityPrompt(label="bending", prompt="a video of a person bending over"),
]


class XClipActivityConfig(BaseModel):
    activities: list[ActivityPrompt] = Field(
        default_factory=lambda: [p.model_copy() for p in DEFAULT_PROMPTS],
        description="Activities to recognise: display label + text prompt for the model")
    clip_seconds: float = Field(2.0, ge=0.5, le=6.0, description="Length of each clip (seconds)")
    stride_seconds: float = Field(1.0, ge=0.25, le=6.0, description="Step between clips (seconds)")
    confidence_threshold: float = Field(
        0.35, ge=0.05, le=0.95, description="Below this the activity is reported as 'uncertain'")
    crop_margin: float = Field(0.15, ge=0.0, le=0.5, description="Extra margin around each person crop")
    max_tracks: int = Field(10, ge=1, le=50, description="Analyse at most this many people (first seen first)")
    max_clips_per_track: int = Field(60, ge=1, le=1000, description="Cap on clips per person (CPU safeguard)")
    batch_size: int = Field(4, ge=1, le=16, description="Clips scored per model call")
    smoothing_windows: int = Field(3, ge=1, le=9, description="Majority filter over neighbouring clips (odd number)")

    @field_validator("activities")
    @classmethod
    def _unique_labels(cls, v: list[ActivityPrompt]) -> list[ActivityPrompt]:
        if len(v) < 2:
            raise ValueError("at least two activities are needed")
        labels = [a.label.strip().lower() for a in v]
        if len(set(labels)) != len(labels):
            raise ValueError("activity labels must be unique")
        if UNCERTAIN in labels:
            raise ValueError(f"'{UNCERTAIN}' is reserved")
        return v


def square_crop(image: np.ndarray, box: list[float], margin: float) -> np.ndarray:
    """Crop the person with a margin, pad to a square (no stretching), resize to 224, BGR->RGB."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    side = max(bw, bh) * (1 + 2 * margin)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    sx1, sy1 = int(round(cx - side / 2)), int(round(cy - side / 2))
    sx2, sy2 = sx1 + int(round(side)), sy1 + int(round(side))
    pad = (max(0, -sy1), max(0, sy2 - h), max(0, -sx1), max(0, sx2 - w))
    crop = image[max(0, sy1):min(h, sy2), max(0, sx1):min(w, sx2)]
    if any(pad):
        crop = cv2.copyMakeBorder(crop, *pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    if crop.size == 0:
        crop = np.zeros((CROP_SIZE, CROP_SIZE, 3), dtype=np.uint8)
    crop = cv2.resize(crop, (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)


class XClipActivityModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="activity_xclip",
        name="Activity Recognition (X-CLIP zero-shot)",
        category="activity",
        version="1.0.0",
        description=(
            "Watches short clips of each tracked person and matches them against text descriptions such as "
            "'a person walking' using Microsoft's X-CLIP video-language model. The activity list is "
            "editable - no training needed. Heavier than the pose-based model; best for comparison."
        ),
        license="MIT (microsoft/xclip-base-patch32)",
        kind="clip",
        requires=[dt.PERSON_DETECTIONS, dt.PERSON_TRACKS],
        produces=[dt.ACTIVITY_SEGMENTS, dt.ACTIVITY_WINDOWS],
        weights=[WEIGHTS],
        config_schema=XClipActivityConfig,
        neural=True,
        default_seconds_per_frame=0.08,
        cost_hint="~0.3-0.8 s per clip per person on CPU; ~790 MB download on first use",
        labels=[p.label for p in DEFAULT_PROMPTS] + [UNCERTAIN],
        method="X-CLIP ViT-B/32, 8 frames per clip, softmax over the text prompts",
        limitations=[
            "Zero-shot: accuracy depends on the wording of the prompts.",
            "Scores are relative to the listed activities only - an unlisted action is forced onto the closest "
            "one unless confidence falls below the threshold.",
            "Small or distant people give low-detail crops and weaker predictions.",
            "Falling is not included; it is only available as a pose-based heuristic.",
        ],
    )

    def __init__(self) -> None:
        super().__init__()
        self._model = None
        self._tokenizer = None

    def load(self, device: str) -> None:
        path = weights.ensure_weights(WEIGHTS)
        try:
            import torch
            from transformers import AutoTokenizer, XCLIPModel

            self._model = XCLIPModel.from_pretrained(str(path)).to(device).eval()
            self._tokenizer = AutoTokenizer.from_pretrained(str(path))
            self._torch = torch
        except Exception as exc:
            raise ModelLoadError(f"Failed to load X-CLIP: {exc}") from exc
        super().load(device)

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        super().unload()

    def weight_hashes(self, config: Any) -> dict[str, str]:
        digest = weights.sha256_of(WEIGHTS)
        return {WEIGHTS.name: digest} if digest else {}

    # ------------------------------------------------------------- per job
    def start_job(self, ctx: JobContext) -> None:
        cfg: XClipActivityConfig = ctx.config
        tok = self._tokenizer([a.prompt for a in cfg.activities], padding=True, return_tensors="pt")
        ctx.state.update({
            "text": {k: v.to(self.device) for k, v in tok.items()},
            "labels": [a.label for a in cfg.activities],
            "buffers": {},        # track id -> deque[(t, crop)]
            "clip_counts": {},    # track id -> clips queued
            "last_kept": {},      # track id -> t of last buffered crop
            "pending": [],        # (track_id, start, end, frames)
            "windows": {},        # track id -> list of windows
            "tracks_seen": [],
        })

    def process_frame(self, frame: FrameData, ctx: JobContext, upstream: dict[str, Any]) -> dict[str, Any]:
        cfg: XClipActivityConfig = ctx.config
        st = ctx.state
        dets = upstream.get(dt.PERSON_DETECTIONS) or []
        interval = cfg.clip_seconds / FRAMES_PER_CLIP
        for tr in upstream.get(dt.PERSON_TRACKS) or []:
            tid, di = tr["id"], tr["det"]
            if di >= len(dets):
                continue
            if tid not in st["buffers"]:
                if len(st["tracks_seen"]) >= cfg.max_tracks:
                    continue
                st["tracks_seen"].append(tid)
                st["buffers"][tid] = deque(maxlen=FRAMES_PER_CLIP)
                st["clip_counts"][tid] = 0
            if st["clip_counts"][tid] >= cfg.max_clips_per_track:
                continue
            buf = st["buffers"][tid]
            last = st["last_kept"].get(tid)
            if last is not None and frame.timestamp - last > cfg.clip_seconds:
                buf.clear()  # person was lost for a while: start a fresh clip
            if last is not None and buf and frame.timestamp - last < interval * 0.95:
                continue
            buf.append((frame.timestamp, square_crop(frame.image, dets[di]["box"], cfg.crop_margin)))
            st["last_kept"][tid] = frame.timestamp
            if len(buf) == FRAMES_PER_CLIP:
                self._queue_clip(tid, list(buf), ctx)
                # Keep the crops that belong to the next clip (start + stride onwards).
                next_start = buf[0][0] + cfg.stride_seconds
                while buf and buf[0][0] < next_start - 1e-6:
                    buf.popleft()
        if len(st["pending"]) >= cfg.batch_size:
            self._score_pending(ctx)
        return {}

    def _queue_clip(self, tid: int, frames: list, ctx: JobContext) -> None:
        ctx.state["pending"].append((tid, frames[0][0], frames[-1][0], [f[1] for f in frames]))
        ctx.state["clip_counts"][tid] += 1

    def _score_pending(self, ctx: JobContext) -> None:
        st = ctx.state
        cfg: XClipActivityConfig = ctx.config
        pending, st["pending"] = st["pending"], []
        if not pending:
            return
        torch = self._torch
        clips = np.stack([np.stack(p[3]) for p in pending]).astype(np.float32) / 255.0  # B,T,H,W,C
        clips = (clips - _CLIP_MEAN) / _CLIP_STD
        pixel_values = torch.from_numpy(clips).permute(0, 1, 4, 2, 3).contiguous().to(self.device)
        with torch.inference_mode():
            out = self._model(pixel_values=pixel_values, **st["text"])
            probs = out.logits_per_video.softmax(dim=-1).cpu().numpy()
        for (tid, start, end, _), p in zip(pending, probs):
            scores = {label: round(float(v), 4) for label, v in zip(st["labels"], p)}
            label, conf = pick_label(scores, cfg.confidence_threshold)
            st["windows"].setdefault(tid, []).append({
                "track_id": tid, "start": round(start, 3), "end": round(end, 3),
                "scores": scores, "label": label, "confidence": round(conf, 3),
            })

    def finish(self, ctx: JobContext) -> dict[str, Any]:
        cfg: XClipActivityConfig = ctx.config
        st = ctx.state
        # Short tracks that never filled a clip: pad by repeating crops if there is enough evidence.
        for tid, buf in st["buffers"].items():
            if st["clip_counts"][tid] == 0 and len(buf) >= FRAMES_PER_CLIP // 2:
                frames = list(buf)
                idx = np.linspace(0, len(frames) - 1, FRAMES_PER_CLIP).round().astype(int)
                self._queue_clip(tid, [frames[i] for i in idx], ctx)
        remaining = st["pending"]
        for i in range(0, len(remaining), cfg.batch_size):
            st["pending"] = remaining[i:i + cfg.batch_size]
            self._score_pending(ctx)
        windows_all, segments_all = [], []
        k = cfg.smoothing_windows if cfg.smoothing_windows % 2 else cfg.smoothing_windows + 1
        for tid in sorted(st["windows"]):
            windows = sorted(st["windows"][tid], key=lambda w: w["start"])
            labels = smooth_labels(windows, k)
            segments_all.extend(windows_to_segments(windows, labels, cfg.stride_seconds, METHOD))
            windows_all.extend(windows)
        return {dt.ACTIVITY_SEGMENTS: segments_all, dt.ACTIVITY_WINDOWS: windows_all}


PLUGIN = XClipActivityModel
