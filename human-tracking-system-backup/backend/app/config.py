"""Application configuration.

All settings can be overridden with environment variables or a ``.env`` file
placed in the ``backend/`` directory (see ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (this file lives in backend/app/config.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Human Detection & Tracking System"
    app_version: str = "1.0.0"
    log_level: str = "INFO"

    # ---- Storage -------------------------------------------------------
    # Relative paths are resolved against the backend/ directory.
    database_url: str = "sqlite:///database/app.db"
    upload_dir: Path = Path("uploads")
    processed_dir: Path = Path("processed")
    model_dir: Path = Path("models")
    temp_dir: Path = Path("tmp")

    max_upload_size_mb: int = 2048
    # Refuse uploads / processing when free disk space would drop below this.
    min_free_disk_mb: int = 500
    upload_chunk_size: int = 1024 * 1024

    # ---- Computer vision -------------------------------------------------
    default_model: str = "yolo11n.pt"
    allowed_models: list[str] = ["yolo11n.pt", "yolo11s.pt"]
    # Download official weights into model_dir the first time they are needed.
    allow_model_download: bool = True
    person_class_id: int = 0
    default_confidence: float = 0.40
    default_frame_skip: int = 0
    max_frame_skip: int = 10
    tracker_config: str = "bytetrack.yaml"
    # "auto" -> CUDA if available, otherwise CPU. Also accepts "cpu", "cuda", "cuda:0", "mps".
    device: str = "auto"
    inference_image_size: int = 640

    # ---- Visualization defaults -----------------------------------------
    box_color_bgr: tuple[int, int, int] = (0, 255, 0)
    show_boxes: bool = True
    show_ids: bool = True
    show_confidence: bool = False

    # ---- Output encoding -------------------------------------------------
    output_crf: int = 23
    output_preset: str = "veryfast"
    keep_audio: bool = True

    # ---- Worker ------------------------------------------------------------
    max_concurrent_jobs: int = 1
    progress_db_interval_seconds: float = 1.0
    event_batch_size: int = 2000

    # ---- API -----------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    allowed_extensions: list[str] = [".mp4", ".avi", ".mov", ".mkv"]

    @field_validator("upload_dir", "processed_dir", "model_dir", "temp_dir", mode="after")
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

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def managed_dirs(self) -> list[Path]:
        return [self.upload_dir, self.processed_dir, self.temp_dir]

    def ensure_directories(self) -> None:
        for d in (self.upload_dir, self.processed_dir, self.model_dir, self.temp_dir):
            d.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            db_path = Path(self.database_url[len("sqlite:///"):])
            if str(db_path) != ":memory:":
                db_path.parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
