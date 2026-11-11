"""Temporal features and transparent scoring for pose-based activity recognition.

All distances are normalised by the person's body height in the window (median
box height), and all rates are per second, so results don't depend on the
video resolution, frame rate or frame interval.

Signals per window:

* ``motion``      body heights per second: hip-centre velocity (least-squares
                  slope) combined with the rate of change of apparent size, so
                  walking towards/away from the camera also counts as motion.
* ``gait``        0-1 strength of left/right ankle alternation. This also detects
                  walking when the camera follows the person (no image motion).
* ``cadence``     foot swaps per second (≈ steps/s), separates walking from running
                  when speed can't be measured.
* ``foot_rise``   how far the lower foot rises above its trend (body heights);
                  both feet leave the ground in a jump.
* ``fall_drop``   largest downward hip movement within 1 s (body heights).
* posture fractions from the pose model (standing / sitting / lying / bending / unknown).

Scores are products of smooth sigmoids over these signals - each activity's
rule is readable in :func:`score_window`. No single frame decides an activity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, Field

L_HIP, R_HIP, L_ANK, R_ANK = 11, 12, 15, 16

ACTIVITIES = ["walking", "running", "jumping", "standing", "sitting", "lying down", "bending", "falling"]
SIZE_RATE_WEIGHT = 3.0  # converts relative size change (1/s) into ~body heights/s at typical distances


class ActivityThresholds(BaseModel):
    stationary_max_speed: float = Field(0.15, ge=0.01, le=1.0, description="Below this (body heights/s) a person is still")
    walk_min_speed: float = Field(0.25, ge=0.05, le=2.0, description="Above this (body heights/s) a person is walking")
    run_min_speed: float = Field(1.4, ge=0.5, le=5.0, description="Above this (body heights/s) a person is running")
    run_min_cadence: float = Field(
        2.6, ge=1.0, le=6.0,
        description="Steps per second above which stepping counts as running (used when the camera follows the person)")
    jump_min_rise: float = Field(0.12, ge=0.03, le=0.6, description="Minimum foot rise (body heights) for a jump")
    fall_min_drop: float = Field(0.35, ge=0.1, le=1.5, description="Minimum hip drop within 1 s (body heights) for a fall")


@dataclass
class TrackSeries:
    t: np.ndarray          # (N,)
    box: np.ndarray        # (N, 4)
    kps: np.ndarray        # (N, 17, 3)
    posture: list[str]


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def _slope(t: np.ndarray, y: np.ndarray) -> float:
    if len(t) < 2 or np.ptp(t) < 1e-6:
        return 0.0
    tc = t - t.mean()
    return float((tc * (y - y.mean())).sum() / (tc * tc).sum())


def window_features(s: TrackSeries, kp_thr: float) -> dict[str, float]:
    t, box, kps = s.t, s.box, s.kps
    heights = np.maximum(1.0, box[:, 3] - box[:, 1])
    h = float(np.median(heights))

    # Hip centre where both hips are visible, otherwise box centre (one source per window).
    hips_ok = (kps[:, L_HIP, 2] >= kp_thr) & (kps[:, R_HIP, 2] >= kp_thr)
    if hips_ok.mean() >= 0.7:
        tt = t[hips_ok]
        px = (kps[hips_ok, L_HIP, 0] + kps[hips_ok, R_HIP, 0]) / 2
        py = (kps[hips_ok, L_HIP, 1] + kps[hips_ok, R_HIP, 1]) / 2
    else:
        tt = t
        px = (box[:, 0] + box[:, 2]) / 2
        py = (box[:, 1] + box[:, 3]) / 2
    v = math.hypot(_slope(tt, px), _slope(tt, py)) / h
    size_rate = abs(_slope(t, np.log(heights)))
    motion = math.hypot(v, SIZE_RATE_WEIGHT * size_rate)

    # Gait and foot rise from ankles (only frames where both ankles are visible).
    # Gait = the feet alternating: the left-right ankle offset oscillates around its mean.
    # Horizontal offset dominates in side views, vertical offset in frontal views; the
    # stronger one is used. It works even when the camera follows the person.
    ank_ok = (kps[:, L_ANK, 2] >= kp_thr) & (kps[:, R_ANK, 2] >= kp_thr)
    gait = 0.0
    cadence = 0.0
    foot_rise = 0.0
    ankles_visible = float(ank_ok.mean())
    if ank_ok.sum() >= 4:
        ta = t[ank_ok]
        span = max(float(ta[-1] - ta[0]), 1e-3)
        best_std, crossings = 0.0, 0
        for axis in (0, 1):
            diff = (kps[ank_ok, L_ANK, axis] - kps[ank_ok, R_ANK, axis]) / h
            std = float(np.std(diff))
            if std > best_std:
                centred = diff - diff.mean()
                signs = np.sign(centred[np.abs(centred) > 0.25 * std])  # ignore jitter near zero
                best_std, crossings = std, int(np.sum(np.diff(signs) != 0))
        gait = min(1.0, best_std / 0.08) * min(1.0, crossings / 2)
        cadence = crossings / span                # foot swaps per second (≈ steps per second)
        la, ra = kps[ank_ok, L_ANK, 1], kps[ank_ok, R_ANK, 1]
        low = np.maximum(la, ra)                  # lower foot (larger y)
        trend = low.mean() + _slope(ta, low) * (ta - ta.mean())
        foot_rise = float(np.max(trend - low)) / h  # how far the lower foot rose above its trend

    # Fall: largest hip drop within 1 s.
    fall_drop = 0.0
    if len(tt) >= 3:
        j = 0
        for i in range(len(tt)):
            while tt[i] - tt[j] > 1.0:
                j += 1
            fall_drop = max(fall_drop, float(py[i] - py[j:i + 1].min()) / h)

    n = len(s.posture)
    frac = {p: s.posture.count(p) / n for p in ("standing", "sitting", "lying down", "bending", "unknown")}
    third = max(1, n // 3)
    frac["lying_start"] = s.posture[:third].count("lying down") / third
    frac["lying_end"] = s.posture[-third:].count("lying down") / third

    return {"motion": motion, "gait": gait, "cadence": cadence, "foot_rise": foot_rise,
            "fall_drop": fall_drop, "ankles_visible": ankles_visible,
            **{f"p_{k}": v for k, v in frac.items()}}


def score_window(f: dict[str, float], th: ActivityThresholds, enable_falling: bool = True) -> dict[str, float]:
    m = f["motion"]
    upright = max(0.0, 1.0 - f["p_sitting"] - f["p_lying down"])
    gait = f["gait"]
    stepping = _sig((gait - 0.5) / 0.1)                      # clear left/right foot alternation
    fast_steps = _sig((f["cadence"] - th.run_min_cadence) / 0.25)
    stationary = _sig((th.stationary_max_speed - m) / 0.04)

    # Two kinds of evidence for locomotion: moving through the image (speed), or
    # stepping in place in the image (camera following the person, treadmill).
    walk_by_speed = _sig((m - th.walk_min_speed) / 0.05) * _sig((th.run_min_speed - m) / 0.12)
    run_by_speed = _sig((m - th.run_min_speed) / 0.12)
    jumping = (_sig((f["foot_rise"] - th.jump_min_rise) / 0.03) * upright
               if f["ankles_visible"] >= 0.5 else 0.0)
    scores = {
        "walking": max(walk_by_speed * (0.85 + 0.15 * gait), stepping * (1 - fast_steps) * 0.9) * upright,
        "running": max(run_by_speed * (0.85 + 0.15 * gait), stepping * fast_steps * 0.85) * upright,
        "jumping": jumping,
        # Standing = still, upright, and neither stepping nor jumping in place.
        "standing": stationary * f["p_standing"] * (1 - stepping) * (1 - jumping),
        "sitting": _sig((0.5 - m) / 0.1) * f["p_sitting"],
        "lying down": _sig((0.6 - m) / 0.15) * f["p_lying down"],
        "bending": _sig((0.5 - m) / 0.1) * f["p_bending"],
    }
    if enable_falling:
        # Upright (or not lying) at the start, lying at the end, with a fast hip drop.
        scores["falling"] = (_sig((f["fall_drop"] - th.fall_min_drop) / 0.05)
                             * f["p_lying_end"] * (1.0 - f["p_lying_start"]))
    return {k: round(min(1.0, v), 4) for k, v in scores.items()}
