"""Rule-based posture classification on synthetic COCO keypoints."""

from app.vision.plugins.human_pose.posture import PostureThresholds, classify_posture

T = PostureThresholds()


def person(points: dict[int, tuple[float, float]], conf: float = 0.9) -> list:
    kps = [[0.0, 0.0, 0.0] for _ in range(17)]
    for i, (x, y) in points.items():
        kps[i] = [x, y, conf]
    return kps


def box_of(kps):
    pts = [(x, y) for x, y, c in kps if c > 0]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return [min(xs) - 5, min(ys) - 15, max(xs) + 5, max(ys) + 5]


def classify(kps):
    return classify_posture(kps, box_of(kps), 0.35, T).label


STANDING = person({5: (95, 50), 6: (105, 50), 11: (96, 100), 12: (104, 100),
                   13: (96, 145), 14: (104, 145), 15: (96, 190), 16: (104, 190)})
SITTING = person({5: (95, 50), 6: (105, 50), 11: (96, 100), 12: (104, 100),     # thighs horizontal,
                  13: (140, 105), 14: (146, 105), 15: (140, 150), 16: (146, 150)})  # shins vertical
LYING = person({5: (50, 100), 6: (50, 110), 11: (100, 102), 12: (100, 112),
                13: (145, 103), 14: (145, 113), 15: (190, 104), 16: (190, 114)})
BENDING = person({5: (140, 70), 6: (145, 75), 11: (100, 100), 12: (104, 100),   # torso ~50 deg forward,
                  13: (100, 145), 14: (104, 145), 15: (100, 190), 16: (104, 190)})  # straight legs


def test_standing():
    assert classify(STANDING) == "standing"


def test_sitting():
    assert classify(SITTING) == "sitting"


def test_lying():
    assert classify(LYING) == "lying down"


def test_bending():
    assert classify(BENDING) == "bending"


def test_unknown_without_hips_or_legs():
    no_hips = [kp if i not in (11, 12) else [0, 0, 0] for i, kp in enumerate(STANDING)]
    assert classify_posture(no_hips, [80, 30, 120, 200], 0.35, T).label == "unknown"
    upper_body_only = person({5: (95, 50), 6: (105, 50), 11: (96, 100), 12: (104, 100)})
    assert classify(upper_body_only) == "unknown"  # upright torso, legs hidden: don't guess


def test_low_confidence_keypoints_are_ignored():
    weak = person({5: (95, 50), 6: (105, 50), 11: (96, 100), 12: (104, 100),
                   13: (96, 145), 14: (104, 145), 15: (96, 190), 16: (104, 190)}, conf=0.1)
    assert classify_posture(weak, box_of(STANDING), 0.35, T).label == "unknown"
