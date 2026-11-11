"""Rule-based posture classification from COCO-17 keypoints.

Geometry used (image y grows downwards):

* **Torso angle**: angle between the shoulder-centre → hip-centre vector and
  the vertical. ~0° upright, ~90° horizontal.
* **Knee angle**: hip-knee-ankle angle; ~180° straight leg.
* **Thigh drop**: vertical hip → knee distance divided by torso length. A
  standing person's knees are well below the hips (~0.8-1.0); a seated
  person's thighs are close to horizontal, so the knees are barely lower.

Labels: ``standing``, ``sitting``, ``lying down``, ``bending``, ``unknown``.
``unknown`` is returned whenever the keypoints needed for a decision are
missing or low-confidence - a label is never forced. Camera angle matters: a
person seated facing the camera, or filmed from above, can be misclassified.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pydantic import BaseModel, Field

L_SH, R_SH, L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANK, R_ANK = 5, 6, 11, 12, 13, 14, 15, 16

STANDING, SITTING, LYING, BENDING, UNKNOWN = "standing", "sitting", "lying down", "bending", "unknown"
POSTURES = [STANDING, SITTING, LYING, BENDING]


class PostureThresholds(BaseModel):
    lying_torso_angle: float = Field(60.0, ge=30, le=89, description="Torso angle (deg) above which a person is lying down")
    bending_torso_angle: float = Field(35.0, ge=10, le=80, description="Torso angle (deg) above which an upright person is bending")
    sitting_thigh_drop: float = Field(0.45, ge=0.1, le=1.0, description="Max knee-below-hip distance (in torso lengths) for sitting")
    standing_thigh_drop: float = Field(0.65, ge=0.2, le=1.5, description="Min knee-below-hip distance (in torso lengths) for standing")
    straight_knee_angle: float = Field(150.0, ge=100, le=180, description="Knee angle (deg) above which a leg counts as straight")
    wide_box_ratio: float = Field(1.25, ge=0.8, le=3.0, description="Box width/height above which a horizontal pose is assumed")


@dataclass
class Posture:
    label: str
    conf: float
    torso_angle: float | None = None

    def as_dict(self) -> dict:
        return {"label": self.label, "conf": round(self.conf, 3)}


def _pt(kps, i, thr):
    x, y, c = kps[i]
    return (x, y, c) if c >= thr else None


def _center(a, b):
    if a and b:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, min(a[2], b[2]))
    return a or b


def _angle(a, b, c) -> float | None:
    """Angle at b (degrees) formed by a-b-c."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return None
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def classify_posture(kps: list, box: list[float], thr: float, t: PostureThresholds) -> Posture:
    """Classify one person's posture. ``kps`` is 17 × [x, y, conf]; ``box`` is [x1, y1, x2, y2]."""
    sh = _center(_pt(kps, L_SH, thr), _pt(kps, R_SH, thr))
    hip = _center(_pt(kps, L_HIP, thr), _pt(kps, R_HIP, thr))
    bw, bh = max(1.0, box[2] - box[0]), max(1.0, box[3] - box[1])
    if not sh or not hip:
        return Posture(UNKNOWN, 0.0)

    dx, dy = hip[0] - sh[0], hip[1] - sh[1]
    torso_len = math.hypot(dx, dy)
    if torso_len < 1e-3:
        return Posture(UNKNOWN, 0.0)
    torso_angle = math.degrees(math.atan2(abs(dx), dy))  # 0 upright; >90 means hips above shoulders
    base_conf = (sh[2] + hip[2]) / 2

    if torso_angle >= t.lying_torso_angle or (bw / bh >= t.wide_box_ratio and torso_angle >= t.bending_torso_angle):
        return Posture(LYING, base_conf, torso_angle)

    # Legs: use whichever side(s) are visible.
    knee_angles, thigh_drops, leg_confs = [], [], []
    for h_i, k_i, a_i in ((L_HIP, L_KNEE, L_ANK), (R_HIP, R_KNEE, R_ANK)):
        h, k = _pt(kps, h_i, thr), _pt(kps, k_i, thr)
        if not (h and k):
            continue
        thigh_drops.append((k[1] - h[1]) / torso_len)
        leg_confs.append(min(h[2], k[2]))
        a = _pt(kps, a_i, thr)
        if a:
            ang = _angle(h, k, a)
            if ang is not None:
                knee_angles.append(ang)

    if torso_angle >= t.bending_torso_angle:
        # Bending forward: inclined torso with legs mostly straight (or legs not visible).
        if not knee_angles or max(knee_angles) >= t.straight_knee_angle - 15:
            return Posture(BENDING, base_conf * (0.8 if not knee_angles else 1.0), torso_angle)
        # Inclined torso with bent knees: crouching/sitting leaning forward - ambiguous.
        return Posture(SITTING, base_conf * 0.6, torso_angle)

    if not thigh_drops:
        return Posture(UNKNOWN, 0.0, torso_angle)  # upright torso but no legs: can't tell
    drop = max(thigh_drops)
    knee = max(knee_angles) if knee_angles else None
    conf = (base_conf + sum(leg_confs) / len(leg_confs)) / 2

    if drop <= t.sitting_thigh_drop and (knee is None or knee < t.straight_knee_angle):
        return Posture(SITTING, conf * (0.85 if knee is None else 1.0), torso_angle)
    if drop >= t.standing_thigh_drop and (knee is None or knee >= t.straight_knee_angle - 20):
        return Posture(STANDING, conf * (0.85 if knee is None else 1.0), torso_angle)
    return Posture(UNKNOWN, 0.0, torso_angle)  # in-between geometry: don't guess
