"""End-to-end API tests: upload → process (real YOLO + ByteTrack) → results → delete."""

import time

import pytest

from app.config import settings

needs_weights = pytest.mark.skipif(
    not (settings.model_dir / "yolo11n.pt").is_file(), reason="yolo11n.pt weights not available"
)


def upload(client, path, **data):
    with open(path, "rb") as f:
        return client.post("/api/videos/upload", files={"file": (path.name, f, "video/mp4")}, data=data)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_rejects_bad_files(client, tmp_root):
    txt = tmp_root / "notes.txt"
    txt.write_text("hello")
    assert upload(client, txt).status_code == 415

    fake = tmp_root / "fake.mp4"
    fake.write_text("definitely not a video")
    r = upload(client, fake)
    assert r.status_code == 415

    empty = tmp_root / "empty.mp4"
    empty.write_bytes(b"")
    assert upload(client, empty).status_code == 422


@needs_weights
def test_full_workflow(client, sample_video):
    r = upload(client, sample_video)
    assert r.status_code == 201, r.text
    video = r.json()
    vid = video["id"]
    assert video["total_frames"] == 30 and video["width"] == 320
    assert "original_video_path" not in video  # paths are never exposed

    dup = upload(client, sample_video)
    assert dup.status_code == 409 and dup.json()["existing_video_id"] == vid

    r = client.post(f"/api/videos/{vid}/process", json={"confidence": 0.4, "frame_skip": 1})
    assert r.status_code == 202, r.text
    assert client.post(f"/api/videos/{vid}/process", json={}).status_code in (409, 202)

    deadline = time.time() + 120
    while time.time() < deadline:
        p = client.get(f"/api/videos/{vid}/progress").json()
        if p["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.5)
    assert p["status"] == "completed", p

    results = client.get(f"/api/videos/{vid}/results").json()
    assert results["video"]["frames_processed"] == 30
    assert results["stats"]["frames_analyzed"] == 15
    assert results["session"]["frame_skip"] == 1

    r = client.get(f"/api/videos/{vid}/processed")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4" and len(r.content) > 0
    r = client.get(f"/api/videos/{vid}/export/csv")
    assert r.status_code == 200 and r.text.startswith("video_id,")
    r = client.get(f"/api/videos/{vid}/export/csv?type=events")
    assert r.status_code == 200 and r.text.startswith("frame_number,")

    stats = client.get("/api/dashboard/stats").json()
    assert stats["completed_videos"] >= 1

    assert client.delete(f"/api/videos/{vid}").status_code == 200
    assert client.get(f"/api/videos/{vid}").status_code == 404


def test_invalid_process_settings(client, sample_video):
    r = upload(client, sample_video, allow_duplicate="true")
    vid = r.json()["id"]
    r = client.post(f"/api/videos/{vid}/process", json={"model_name": "evil.pt"})
    assert r.status_code == 422
    r = client.post(f"/api/videos/{vid}/process", json={"frame_skip": 99})
    assert r.status_code == 422
    assert client.post(f"/api/videos/{vid}/cancel").status_code == 409
