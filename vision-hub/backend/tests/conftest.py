"""Test configuration: isolated storage and database, fake plugins, generated videos.

Tests never download weights. Model plumbing is exercised with fake plugins
(``tests/fakes.py``); tests needing real weights are marked ``real_weights`` and
skipped when the weights are not already present.
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

BACKEND = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="vision-hub-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "STORAGE_DIR": str(_TMP / "storage"),
    "MODEL_WEIGHTS_DIR": str(BACKEND / "model_weights"),  # reuse real weights if present (read-only)
    "ALLOW_MODEL_DOWNLOAD": "false",
    "MIN_FREE_DISK_MB": "1",
    "KEEP_AUDIO": "false",
    "WORKER_POLL_SECONDS": "0.2",
    "TORCH_THREADS": "2",
})
sys.path.insert(0, str(BACKEND))


def make_video(path: Path, frames: int = 45, size=(320, 240), fps: float = 15.0) -> Path:
    """A small synthetic video (mp4v codec, so scanning has to create an H.264 playback copy)."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(frames):
        frame = np.full((size[1], size[0], 3), 40, dtype=np.uint8)
        cv2.rectangle(frame, (20 + i * 3, 60), (60 + i * 3, 200), (200, 200, 200), -1)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def sample_video(tmp_root) -> Path:
    return make_video(tmp_root / "sample.mp4")


@pytest.fixture(scope="session", autouse=True)
def fake_plugins():
    from app.vision.model_registry import registry
    from tests.fakes import FAKES

    registry.discover()
    for cls in FAKES:
        registry.register(cls)
    yield
    for cls in FAKES:
        registry.unregister(cls.spec.model_id)


@pytest.fixture(scope="session")
def client(fake_plugins):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def worker(client):
    """The analysis worker, running in a background thread for API tests."""
    from app.workers.analysis_worker import AnalysisWorker

    w = AnalysisWorker()
    t = threading.Thread(target=w.run_forever, daemon=True)
    t.start()
    yield w
    w.stop()
    t.join(10)
