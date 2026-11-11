"""Test configuration: isolated temporary storage and database per test session."""

import os
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

_TMP = Path(tempfile.mkdtemp(prefix="tracker-tests-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "PROCESSED_DIR": str(_TMP / "processed"),
    "TEMP_DIR": str(_TMP / "tmp"),
    # Reuse real weights from backend/models so detection tests run offline.
    "MODEL_DIR": str(Path(__file__).resolve().parents[1] / "models"),
    "MIN_FREE_DISK_MB": "1",
    "KEEP_AUDIO": "false",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_video(path: Path, frames: int = 30, size=(320, 240), fps: float = 15.0) -> Path:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(frames):
        frame = np.full((size[1], size[0], 3), 40, dtype=np.uint8)
        cv2.circle(frame, (20 + i * 5 % size[0], size[1] // 2), 15, (200, 200, 200), -1)
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture(scope="session")
def tmp_root() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def sample_video(tmp_root) -> Path:
    return make_video(tmp_root / "sample.mp4")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
