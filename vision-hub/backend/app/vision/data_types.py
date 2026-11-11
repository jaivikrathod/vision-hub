"""Named data types that models exchange.

Models declare which data types they ``require`` and ``produce``; the pipeline
planner uses these names to order models and auto-add providers. Values are
plain JSON-serialisable structures so they can be streamed to result files and
to the browser without conversion.

Per-frame types (one value per processed frame, aligned by detection index):

* ``person_detections``  list[{"box": [x1, y1, x2, y2], "conf": float}]
* ``person_keypoints``   list[list[[x, y, conf] * 17]]  (COCO order, aligned with detections)
* ``posture_labels``     list[{"label": str, "conf": float}]  (aligned with detections)
* ``person_tracks``      list[{"det": int, "id": int}]  (detection index -> track id)

Job-level types (produced once per job, at the end):

* ``track_summaries``    list[{"track_id", "first_seen", "last_seen", "frame_count",
                               "avg_confidence", "trajectory": [[t, cx, cy], ...]}]
* ``activity_segments``  list[{"track_id", "start", "end", "label", "confidence", "method"}]
* ``activity_windows``   list[{"track_id", "start", "end", "scores": {label: score}, "label", "confidence"}]

Coordinates are pixels in the *processing frame* (the video frame after any
downscaling; its size is recorded in each result's metadata).
"""

from __future__ import annotations

PERSON_DETECTIONS = "person_detections"
PERSON_KEYPOINTS = "person_keypoints"
POSTURE_LABELS = "posture_labels"
PERSON_TRACKS = "person_tracks"

TRACK_SUMMARIES = "track_summaries"
ACTIVITY_SEGMENTS = "activity_segments"
ACTIVITY_WINDOWS = "activity_windows"

FRAME_TYPES = {PERSON_DETECTIONS, PERSON_KEYPOINTS, POSTURE_LABELS, PERSON_TRACKS}
JOB_TYPES = {TRACK_SUMMARIES, ACTIVITY_SEGMENTS, ACTIVITY_WINDOWS}

DESCRIPTIONS = {
    PERSON_DETECTIONS: "Person bounding boxes with confidence, per frame",
    PERSON_KEYPOINTS: "17 COCO body keypoints per detected person, per frame",
    POSTURE_LABELS: "Per-frame posture (standing / sitting / lying down / bending / unknown)",
    PERSON_TRACKS: "Consistent temporary person IDs across frames",
    TRACK_SUMMARIES: "Per-person first/last seen, frame count and trajectory",
    ACTIVITY_SEGMENTS: "Per-person activity time ranges with confidence",
    ACTIVITY_WINDOWS: "Raw per-window activity scores (before smoothing)",
}

# COCO-17 keypoint names and skeleton edges (used by the posture rules and the annotator).
KEYPOINT_NAMES = [
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle",
]
SKELETON = [
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),        # arms
    (5, 11), (6, 12), (11, 12),                      # torso
    (11, 13), (13, 15), (12, 14), (14, 16),          # legs
    (0, 1), (0, 2), (1, 3), (2, 4),                  # head
]
