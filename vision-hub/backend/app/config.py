"""Application configuration.

All settings can be overridden with environment variables or a ``.env`` file
placed in the ``backend/`` directory (see ``.env.example``). Relative paths are
resolved against ``backend/``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (this file lives in backend/app/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _default_threads() -> int:
    # Leave a couple of cores free so the API, browser and desktop stay responsive.
    return max(1, (os.cpu_count() or 2) - 2)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    app_name: str = "Vision Hub"
    app_version: str = "2.0.0"
    log_level: str = "INFO"

    # ---- Storage ---------------------------------------------------------
    database_url: str = "sqlite:///database/vision_hub.db"
    storage_dir: Path = Path("storage")
    model_weights_dir: Path = Path("model_weights")

    max_upload_size_mb: int = 2048
    min_free_disk_mb: int = 500
    upload_chunk_size: int = 1024 * 1024
    allowed_extensions: list[str] = [".mp4", ".avi", ".mov", ".mkv"]

    # ---- Limits (CPU-friendly) ---------------------------------------------
    max_video_duration_seconds: float = 600.0     # 10 minutes
    max_inference_height: int = 1080              # taller frames are downscaled for inference
    results_retention_days: int = 0               # 0 = keep forever; >0 enables cleanup endpoint default

    # ---- Inference -----------------------------------------------------------
    # "auto" -> CUDA if available, otherwise CPU. Also: "cpu", "cuda", "cuda:0", "mps".
    device: str = "auto"
    torch_threads: int = _default_threads()
    allow_model_download: bool = True
    # Maximum number of neural-network models kept loaded at the same time.
    max_loaded_models: int = 2
    result_chunk_seconds: float = 10.0

    # ---- Output encoding -----------------------------------------------------
    output_crf: int = 23
    output_preset: str = "veryfast"
    keep_audio: bool = True

    # ---- Worker ----------------------------------------------------------------
    worker_poll_seconds: float = 1.0
    worker_heartbeat_seconds: float = 2.0
    # A processing job whose heartbeat is older than this is considered dead.
    worker_stale_seconds: float = 60.0
    progress_db_interval_seconds: float = 0.75

    # ---- API ---------------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @field_validator("storage_dir", "model_weights_dir", mode="after")
    @classmethod
    def _absolute_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @field_validator("database_url", mode="after")
    @classmethod
    def _absolute_sqlite(cls, value: str) -> str:
        prefix = "sqlite:///"
        if value.startswith(prefix) and not value.startswith(prefix + "/"):
            path = value[len(prefix):]
            if path != ":memory:":
                return prefix + str((BACKEND_DIR / path).resolve())
        return value

    # ---- Derived directories ----------------------------------------------------
    @property
    def upload_dir(self) -> Path:
        return self.storage_dir / "uploads"

    @property
    def playback_dir(self) -> Path:
        return self.storage_dir / "playback"

    @property
    def thumbnail_dir(self) -> Path:
        return self.storage_dir / "thumbnails"

    @property
    def results_dir(self) -> Path:
        return self.storage_dir / "results"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    @property
    def temp_dir(self) -> Path:
        return self.storage_dir / "tmp"

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def managed_dirs(self) -> list[Path]:
        """Directories from which files may be served or deleted."""
        return [self.upload_dir, self.playback_dir, self.thumbnail_dir, self.results_dir,
                self.exports_dir, self.temp_dir]

    def ensure_directories(self) -> None:
        for d in (*self.managed_dirs, self.model_weights_dir):
            d.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url[len("sqlite:///"):])
            if str(db_path) != ":memory:":
                db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
