"""Pose-based activity features, scoring, smoothing and segments (synthetic sequences)."""

import numpy as np
import pytest

from app.vision.activity_utils import UNCERTAIN, pick_label, smooth_labels, window_starts, windows_to_segments
from app.vision.plugins.activity_pose_temporal.features import (
    ActivityThresholds,
    TrackSeries,
    score_window,
    window_features,
)
from tests.fakes import walking_person

TH = ActivityThresholds()


def series(fn, seconds=1.5, fps=15, posture="standing"):
    t = np.arange(0, seconds, 1 / fps)
    boxes, kps = zip(*(fn(x) for x in t))
    return TrackSeries(t, np.asarray(boxes, float), np.asarray(kps, float), [posture] * len(t))


def top(s, posture_label=None):
    scores = score_window(window_features(s, 0.35), TH)
    return pick_label(scores, 0.45)[0], scores


def test_walking_through_the_image():
    label, _ = top(series(lambda t: walking_person(t, speed=80)))  # 0.5 body heights/s
    assert label == "walking"


def test_walking_with_camera_following_is_detected_from_gait():
    # No movement across the image, but feet alternate (camera tracks the person).
    label, scores = top(series(lambda t: walking_person(t, speed=0.0001)))
    assert label == "walking", scores


def test_standing_still():
    def still(t):
        box, kps = walking_person(0.0, speed=0)
        return box, kps
    label, scores = top(series(still))
    assert label == "standing", scores


def test_running_by_speed():
    label, _ = top(series(lambda t: walking_person(t, speed=320)))  # 2 body heights/s
    assert label == "running"


def test_sitting_and_lying_follow_posture_when_still():
    still = lambda t: walking_person(0.0, speed=0)  # noqa: E731
    assert top(series(still, posture="sitting"))[0] == "sitting"
    assert top(series(still, posture="lying down"))[0] == "lying down"


def test_jump_needs_foot_rise():
    def jump(t):
        box, kps = walking_person(0.0, speed=0)
        lift = 40 * max(0.0, np.sin(np.pi * (t - 0.5) / 0.5)) if 0.5 <= t <= 1.0 else 0.0
        box = [box[0], box[1] - lift, box[2], box[3] - lift]
        kps = [[x, y - lift, c] for x, y, c in kps]
        return box, kps
    label, scores = top(series(jump))
    assert label == "jumping", scores


def test_fall_heuristic():
    def fall(t):
        box, kps = walking_person(0.0, speed=0)
        drop = 0 if t < 0.5 else min(1.0, (t - 0.5) / 0.4) * 90  # hips drop 90 px (0.56 h) in 0.4 s
        return box, [[x, y + (drop if i >= 11 else drop * 0.6), c] for i, (x, y, c) in enumerate(kps)]
    s = series(fall)
    s.posture = ["standing"] * 9 + ["lying down"] * (len(s.t) - 9)
    label, scores = top(s)
    assert label == "falling", scores


def test_uncertain_when_evidence_is_weak():
    assert pick_label({"walking": 0.3, "standing": 0.2}, 0.45) == (UNCERTAIN, 0.3)


def test_window_starts_cover_track():
    assert window_starts(0.0, 1.0, 1.5, 0.5) == [0.0]
    starts = window_starts(0.0, 4.2, 1.5, 0.5)
    assert starts[0] == 0.0 and starts[-1] + 1.5 >= 4.2 - 0.25


def test_smoothing_removes_single_flicker():
    ws = [{"label": x} for x in ["walking", "walking", "running", "walking", "walking"]]
    assert smooth_labels(ws, 3) == ["walking"] * 5
    assert smooth_labels(ws, 1) == [w["label"] for w in ws]


def test_segments_are_contiguous_and_merged():
    windows = [{"track_id": 1, "start": s, "end": s + 1.5, "label": lab, "confidence": 0.8,
                "scores": {lab: 0.8}} for s, lab in [(0, "walking"), (0.5, "walking"), (1.0, "running"),
                                                    (1.5, "running")]]
    segs = windows_to_segments(windows, [w["label"] for w in windows], 0.5, "test")
    assert [s["label"] for s in segs] == ["walking", "running"]
    assert segs[0]["start"] == 0 and segs[-1]["end"] == 3.0
    assert segs[0]["end"] == segs[1]["start"]  # no gap


def test_segments_merge_with_real_world_timestamps():
    # Timestamps at 29.97 fps / interval 2 are not round numbers.
    starts = [round(i * 0.5005, 4) for i in range(8)]
    windows = [{"track_id": 1, "start": s, "end": round(s + 1.4681, 4), "label": "walking", "confidence": 0.8,
                "scores": {"walking": 0.8}} for s in starts]
    segs = windows_to_segments(windows, ["walking"] * 8, 0.5, "test")
    assert len(segs) == 1 and segs[0]["start"] == 0 and segs[0]["end"] == pytest.approx(windows[-1]["end"], abs=1e-3)


def test_segments_break_at_gaps():
    windows = [{"track_id": 1, "start": s, "end": s + 1.5, "label": "walking", "confidence": 0.8,
                "scores": {"walking": 0.8}} for s in (0.0, 5.0)]
    segs = windows_to_segments(windows, ["walking", "walking"], 0.5, "test")
    assert len(segs) == 2 and segs[0]["end"] == pytest.approx(1.5)
