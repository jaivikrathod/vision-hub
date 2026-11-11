"""ByteTrack adapter (pins the internal Ultralytics API we rely on) and chunked result store."""

from app.vision.plugins.human_tracking.bytetrack_adapter import ByteTrackAdapter, TrackerSettings
from app.vision.result_store import JobResultStore


def test_bytetrack_adapter_keeps_ids_and_maps_detection_indices():
    tracker = ByteTrackAdapter(TrackerSettings())
    ids_by_x = {}
    for f in range(10):
        a = [10 + f * 3, 10, 60 + f * 3, 120]      # person moving right
        b = [200 - f * 2, 30, 250 - f * 2, 140]    # person moving left
        order = [a, b] if f % 2 == 0 else [b, a]  # detection order changes between frames
        pairs = tracker.update(order, [0.9, 0.85])
        assert len(pairs) == 2
        for det_idx, tid in pairs:
            side = "a" if order[det_idx] is a else "b"
            ids_by_x.setdefault(side, set()).add(tid)
    assert len(ids_by_x["a"]) == 1 and len(ids_by_x["b"]) == 1
    assert ids_by_x["a"] != ids_by_x["b"]
    assert tracker.update([], []) == []


def test_result_store_chunks_ranges_and_merging(tmp_path):
    store = JobResultStore(tmp_path / "job", chunk_seconds=10)
    wa, wb = store.writer("a"), store.writer("b")
    for f in range(0, 750, 5):  # 25 s at 30 fps, every 5th frame
        t = f / 30
        wa.write(f, t, {"x": [f]})
        wb.write(f, t, {"y": [f * 2]})
    wa.close(), wb.close()
    wa.write_meta({"frames_written": wa.frames_written, "kind": "frame"})
    assert sorted(p.name for p in (tmp_path / "job" / "a").glob("chunk_*")) == [
        "chunk_00000.jsonl.gz", "chunk_00001.jsonl.gz", "chunk_00002.jsonl.gz"]

    middle = list(store.iter_model("a", 12.0, 14.0))
    assert middle and all(12.0 <= r["t"] <= 14.0 for r in middle)

    merged = list(store.iter_merged(["a", "b"], 0, 1))
    assert merged[0] == (0, 0.0, {"x": [0], "y": [0]})
    assert store.reader(["a"]).frame_count() == 150


def test_truncated_chunk_is_tolerated(tmp_path):
    store = JobResultStore(tmp_path / "job")
    w = store.writer("a")
    for f in range(20):
        w.write(f, f / 10, {"x": f})
    w.close()
    chunk = tmp_path / "job" / "a" / "chunk_00000.jsonl.gz"
    data = chunk.read_bytes()
    chunk.write_bytes(data[: len(data) - 12])  # simulate a crash mid-write
    records = list(store.iter_model("a"))
    assert 0 < len(records) <= 20
