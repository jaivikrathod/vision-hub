"""Real-weight integration test. Skipped when the weights are not already downloaded
(tests never download). Run ``python scripts/download_weights.py`` first to enable it."""

import pytest

from app.config import settings
from app.vision.model_executor import JobOptions, ModelExecutor
from app.vision.model_manager import ModelManager
from app.vision.pipeline_planner import plan_pipeline
from app.vision.result_store import JobResultStore

real_weights = pytest.mark.skipif(not (settings.model_weights_dir / "yolo11n-pose.pt").is_file(),
                                  reason="yolo11n-pose.pt not downloaded")


@real_weights
def test_real_pose_tracking_activity_pipeline_runs(sample_video, tmp_path):
    pipeline = plan_pipeline(["activity_pose_temporal"])  # auto-adds the real pose + tracking models
    assert pipeline.model_ids == ["human_pose", "human_tracking", "activity_pose_temporal"]
    ex = ModelExecutor(1, sample_video, pipeline, JobOptions(frame_interval=3, render_video=False),
                       ModelManager(), JobResultStore(tmp_path / "r"), "cpu")
    res = ex.run()
    assert all(r.status == "completed" for r in res.runs.values())
    assert len(res.runs["human_pose"].weight_hashes["yolo11n-pose.pt"]) == 64
    # The synthetic video contains no people: the models must not invent any.
    assert res.detection_count == 0 and res.valid_track_ids == set()
