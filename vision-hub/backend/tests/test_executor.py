"""Model executor with fake plugins: single pass, post models, failures, cancellation, rendering."""

import cv2
import pytest

from app.core.exceptions import ProcessingCancelled
from app.vision import data_types as dt
from app.vision.model_executor import Callbacks, JobOptions, ModelExecutor
from app.vision.model_manager import ModelManager
from app.vision.pipeline_planner import plan_pipeline
from app.vision.result_store import JobResultStore


def run(sample_video, tmp_path, models, configs=None, options=None, callbacks=None):
    pipeline = plan_pipeline(models, configs or {})
    store = JobResultStore(tmp_path / "results", 1.0)
    ex = ModelExecutor(1, sample_video, pipeline, options or JobOptions(render_video=False), ModelManager(),
                       store, "cpu", callbacks)
    return ex.run(), store


def test_pipeline_runs_fake_pose_real_tracking_and_activity(sample_video, tmp_path):
    progress = []
    res, store = run(sample_video, tmp_path, ["fake_pose", "human_tracking", "activity_pose_temporal"],
                     options=JobOptions(frame_interval=1, render_video=True),
                     callbacks=Callbacks(on_progress=lambda f, s, d: progress.append(f)))
    assert {m: r.status for m, r in res.runs.items()} == {
        "fake_pose": "completed", "human_tracking": "completed", "activity_pose_temporal": "completed"}
    assert res.frames_decoded == 45 and res.frames_processed == 45
    assert res.valid_track_ids == {1}
    assert res.detection_count == len([s for s in res.frame_stats if s[2] == 1])
    assert progress == sorted(progress) and progress[-1] < 1.0

    segs = res.outputs_of_type(dt.ACTIVITY_SEGMENTS)["activity_pose_temporal"]
    assert segs and segs[0]["label"] == "walking" and segs[0]["track_id"] == 1
    # Per-frame results are chunked (1 s chunks here) and merge across models by frame.
    assert len(list((tmp_path / "results" / "fake_pose").glob("chunk_*"))) == 3
    f, t, data = next(store.iter_merged(["fake_pose", "human_tracking"]))
    assert data[dt.PERSON_TRACKS] == [{"det": 0, "id": 1}]
    # Annotated video: full length, processing resolution.
    cap = cv2.VideoCapture(str(res.annotated_video))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 45 and int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) == 320
    cap.release()


def test_frame_interval_processes_fewer_frames(sample_video, tmp_path):
    res, _ = run(sample_video, tmp_path, ["fake_pose", "human_tracking"],
                 options=JobOptions(frame_interval=3, render_video=False))
    assert res.frames_decoded == 45 and res.frames_processed == 15


def test_failure_skips_dependents_but_independent_models_finish(sample_video, tmp_path):
    res, _ = run(sample_video, tmp_path, ["fake_pose", "human_tracking", "fake_counter", "fake_brightness"],
                 {"fake_pose": {"fail_on_frame": 5}})
    assert res.runs["fake_pose"].status == "failed" and "boom" in res.runs["fake_pose"].error
    assert res.runs["human_tracking"].status == "skipped"
    assert res.runs["fake_counter"].status == "skipped"
    assert res.runs["fake_brightness"].status == "completed"


def test_all_models_failing_fails_the_job(sample_video, tmp_path):
    from app.core.exceptions import ProcessingError

    with pytest.raises(ProcessingError, match="No model could run.*boom"):
        run(sample_video, tmp_path, ["fake_pose", "human_tracking"], {"fake_pose": {"fail_on_frame": 0}})


def test_post_model_reads_stored_results(sample_video, tmp_path):
    res, _ = run(sample_video, tmp_path, ["fake_pose", "fake_counter"])  # auto-adds tracking
    assert res.runs["human_tracking"].status == "completed"
    assert res.runs["fake_counter"].status == "completed"
    counts = res.runs["fake_counter"].outputs["fake_counts"]
    assert sum(counts.values()) > 0


def test_cancellation(sample_video, tmp_path):
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(ProcessingCancelled):
        run(sample_video, tmp_path, ["fake_pose"], callbacks=Callbacks(is_cancelled=cancelled))


def test_short_tracks_are_dropped_with_their_activities(sample_video, tmp_path):
    res, _ = run(sample_video, tmp_path, ["fake_pose", "human_tracking", "activity_pose_temporal"],
                 {"human_tracking": {"min_track_seconds": 10}})
    assert res.valid_track_ids == set()
    assert res.outputs_of_type(dt.ACTIVITY_SEGMENTS)["activity_pose_temporal"] == []


def test_runtime_estimate_scales_with_model_configuration():
    from app.vision.model_executor import estimate_stages

    def decode_seconds(image_size):
        p = plan_pipeline(["human_pose"], {"human_pose": {"image_size": image_size}})
        return estimate_stages(p, 300, 1, 1920, 1080, False, {"human_pose": 0.1})["decode"]

    assert decode_seconds(1280) > decode_seconds(960) > decode_seconds(640)
    # Benchmarks are normalised to the default config (960): 300 frames x 0.1 s + decoding.
    assert decode_seconds(960) == pytest.approx(300 * 0.1 + 300 * 0.004, rel=1e-6)
