"""End-to-end API tests with the worker running in a background thread (fake plugins, no downloads)."""

import time

import pytest


def upload(client, path, **data):
    with open(path, "rb") as f:
        return client.post("/api/videos/upload", files={"file": (path.name, f, "video/mp4")}, data=data)


def wait_for(fn, predicate, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if predicate(value):
            return value
        time.sleep(0.2)
    raise AssertionError(f"Timed out; last value: {value}")


@pytest.fixture(scope="module")
def ready_video(client, sample_video):
    r = upload(client, sample_video)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    v = wait_for(lambda: client.get(f"/api/videos/{vid}").json(), lambda v: v["status"] in ("ready", "failed"))
    assert v["status"] == "ready", v
    return v


def test_health_and_system(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    info = client.get("/api/system").json()
    assert info["max_video_duration_seconds"] == 600


def test_rejects_bad_files(client, tmp_root):
    txt = tmp_root / "notes.txt"
    txt.write_text("hello")
    assert upload(client, txt).status_code == 415
    fake = tmp_root / "fake.mp4"
    fake.write_text("definitely not a video")
    assert upload(client, fake).status_code == 415
    empty = tmp_root / "empty.mp4"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 422


def test_upload_scan_and_playback(client, ready_video, sample_video):
    v = ready_video
    assert v["total_frames"] == 45 and v["width"] == 320 and v["codec"] == "mpeg4"
    assert v["uses_playback_copy"] is True  # mp4v isn't browser-playable -> H.264 copy
    assert v["has_thumbnail"] is True
    assert "file_path" not in v  # paths are never exposed
    r = client.get(f"/api/videos/{v['id']}/stream", headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and len(r.content) == 100
    assert client.get(f"/api/videos/{v['id']}/thumbnail").headers["content-type"] == "image/jpeg"
    dup = upload(client, sample_video)
    assert dup.status_code == 409 and dup.json()["existing_video_id"] == v["id"]


def test_models_api(client):
    models = {m["model_id"]: m for m in client.get("/api/models").json()}
    assert {"human_pose", "human_tracking", "activity_pose_temporal", "activity_xclip"} <= set(models)
    pose = client.get("/api/models/human_pose").json()
    assert pose["config_schema"]["properties"]["confidence"]["maximum"] == 0.95
    assert pose["license"].startswith("AGPL")
    cfg = client.get("/api/models/activity_xclip/configuration").json()
    assert "falling" not in [a["label"] for a in cfg["default_config"]["activities"]]
    assert client.get("/api/models/nope").status_code == 404


def test_plan_reports_auto_added_models_and_estimate(client, ready_video):
    r = client.post("/api/analysis/plan", json={"video_id": ready_video["id"], "models": ["activity_pose_temporal"]})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["steps"][-1]["model_id"] == "activity_pose_temporal"
    assert "human_tracking" in plan["auto_added"]
    assert plan["estimated_seconds"] > 0 and plan["frames_to_process"] == 45
    bad = client.post("/api/analysis/plan", json={"video_id": ready_video["id"], "models": ["human_pose"],
                                                  "configs": {"human_pose": {"confidence": 7}}})
    assert bad.status_code == 422 and "Invalid configuration" in bad.json()["detail"]


def test_full_analysis_workflow(client, worker, ready_video):
    req = {"video_id": ready_video["id"], "models": ["fake_pose", "human_tracking", "activity_pose_temporal"],
           "options": {"frame_interval": 1, "render_video": True}}
    r = client.post("/api/analysis/start", json=req)
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]

    job = wait_for(lambda: client.get(f"/api/analysis/{job_id}").json(),
                   lambda j: j["status"] in ("completed", "failed", "cancelled"))
    assert job["status"] == "completed", job
    assert all(m["execution_status"] == "completed" for m in job["models"])
    assert job["has_annotated_video"] and job["device"] == "cpu"

    res = client.get(f"/api/analysis/{job_id}/results").json()
    assert res["unique_people"] == 1 and res["frames_processed"] == 45
    assert res["posture_distribution"] == {"standing": res["total_detections"]}
    assert res["activity_models"][0]["distribution_seconds"].get("walking", 0) > 1.0
    assert "skeleton" in res["available_overlays"] and "activity" in res["available_overlays"]
    assert res["people_over_time"]

    frames = client.get(f"/api/analysis/{job_id}/frames?start=0&end=1").json()
    assert frames["coord_width"] == 320 and len(frames["frames"]) == 16
    person = frames["frames"][0]["persons"][0]
    assert person["track_id"] == 1 and len(person["keypoints"]) == 17

    persons = client.get(f"/api/analysis/{job_id}/persons").json()
    assert persons[0]["dominant_activity"]["activity_pose_temporal"] == "walking"
    acts = client.get(f"/api/analysis/{job_id}/activities").json()
    assert acts["segments"] and acts["segments"][0]["method"] == "pose-temporal"

    video = client.get(f"/api/analysis/{job_id}/annotated-video")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"

    # SSE stream of a finished job ends immediately with an `end` event.
    with client.stream("GET", f"/api/analysis/{job_id}/progress") as s:
        body = "".join(s.iter_text())
    assert "event: end" in body and '"status": "completed"' in body

    dash = client.get("/api/dashboard").json()
    assert dash["jobs_by_status"]["completed"] >= 1 and dash["worker"]["alive"] is True

    # Reproducibility: every job model records version and configuration.
    assert job["models"][0]["model_version"] == "0.0.1" and "speed" in job["models"][0]["configuration"]


def test_cancel_queued_job_and_delete_rules(client, ready_video, worker):
    worker.stop_event.set()  # pause the worker loop so the job stays queued
    time.sleep(0.5)
    try:
        r = client.post("/api/analysis/start", json={"video_id": ready_video["id"], "models": ["fake_pose"]})
        job_id = r.json()["id"]
        assert client.get(f"/api/analysis/{job_id}").json()["queue_position"] == 1
        assert client.delete(f"/api/videos/{ready_video['id']}").status_code == 409  # active job
        assert client.post(f"/api/analysis/{job_id}/cancel").status_code == 200
        assert client.get(f"/api/analysis/{job_id}").json()["status"] == "cancelled"
        assert client.post(f"/api/analysis/{job_id}/cancel").status_code == 409
        assert client.get(f"/api/analysis/{job_id}/results").status_code == 409
        assert client.delete(f"/api/analysis/{job_id}").status_code == 200
    finally:
        worker.stop_event.clear()


def test_failed_model_is_reported(client, ready_video):
    import threading

    from app.workers.analysis_worker import AnalysisWorker

    w = AnalysisWorker()
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    try:
        r = client.post("/api/analysis/start", json={
            "video_id": ready_video["id"], "models": ["fake_pose", "human_tracking"],
            "configs": {"fake_pose": {"fail_on_frame": 0}}, "options": {"render_video": False}})
        job_id = r.json()["id"]
        job = wait_for(lambda: client.get(f"/api/analysis/{job_id}").json(),
                       lambda j: j["status"] in ("completed", "failed"))
        assert job["status"] == "failed" and "boom" in job["error_message"]
        statuses = {m["model_id"]: m["execution_status"] for m in job["models"]}
        assert statuses == {"fake_pose": "failed", "human_tracking": "skipped"}
    finally:
        w.stop()
        t.join(10)


def test_delete_video_removes_jobs(client, sample_video):
    r = upload(client, sample_video, allow_duplicate="true")
    vid = r.json()["id"]
    wait_for(lambda: client.get(f"/api/videos/{vid}").json(), lambda v: v["status"] == "ready")
    assert client.delete(f"/api/videos/{vid}").status_code == 200
    assert client.get(f"/api/videos/{vid}").status_code == 404
