"""YOLO model management: device selection, weight resolution and loading."""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.core.exceptions import ModelWeightsMissingError

logger = logging.getLogger(__name__)

_download_lock = threading.Lock()
_ultralytics_configured = False


def _configure_ultralytics() -> None:
    global _ultralytics_configured
    if _ultralytics_configured:
        return
    # Privacy: make sure Ultralytics never sends usage analytics.
    try:
        from ultralytics import settings as yolo_settings

        if yolo_settings.get("sync", False):
            yolo_settings.update({"sync": False})
    except Exception as exc:  # pragma: no cover - depends on ultralytics version
        logger.debug("Could not update Ultralytics settings: %s", exc)
    try:
        from ultralytics.utils import events as yolo_events

        yolo_events.events.enabled = False
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not disable Ultralytics events: %s", exc)
    _ultralytics_configured = True


@lru_cache(maxsize=1)
def cuda_info() -> tuple[bool, str | None]:
    try:
        import torch

        if torch.cuda.is_available():
            return True, torch.cuda.get_device_name(0)
    except Exception as exc:  # pragma: no cover
        logger.warning("CUDA check failed: %s", exc)
    return False, None


def select_device(preference: str | None = None) -> str:
    """Resolve the inference device. 'auto' picks CUDA when available, else CPU."""
    pref = (preference or settings.device or "auto").lower()
    cuda_ok, _ = cuda_info()
    if pref == "auto":
        return "cuda:0" if cuda_ok else "cpu"
    if pref.startswith("cuda") and not cuda_ok:
        logger.warning("CUDA requested but not available; falling back to CPU")
        return "cpu"
    if pref == "mps":
        try:
            import torch

            if not torch.backends.mps.is_available():
                return "cpu"
        except Exception:
            return "cpu"
    return pref


def installed_models() -> list[str]:
    return [m for m in settings.allowed_models if (settings.model_dir / m).is_file()]


def resolve_weights(model_name: str) -> Path:
    """Return the local weight file, downloading the official weights once if allowed."""
    if model_name not in settings.allowed_models:
        raise ModelWeightsMissingError(f"Model '{model_name}' is not allowed.")
    path = settings.model_dir / model_name
    if path.is_file() and path.stat().st_size > 0:
        return path
    if not settings.allow_model_download:
        raise ModelWeightsMissingError(
            f"Model weights '{model_name}' not found in {settings.model_dir.name}/. "
            "Download them (see README) or set ALLOW_MODEL_DOWNLOAD=true."
        )
    with _download_lock:
        if path.is_file() and path.stat().st_size > 0:
            return path
        logger.info("Downloading model weights %s (one-time)…", model_name)
        try:
            _configure_ultralytics()
            from ultralytics.utils.downloads import attempt_download_asset

            settings.model_dir.mkdir(parents=True, exist_ok=True)
            attempt_download_asset(str(path))
        except Exception as exc:
            logger.exception("Weight download failed")
            raise ModelWeightsMissingError(
                f"Model weights '{model_name}' are missing and could not be downloaded: {exc}. "
                f"Place the file in backend/{settings.model_dir.name}/ manually."
            ) from exc
    if not path.is_file():
        raise ModelWeightsMissingError(f"Model weights '{model_name}' could not be found after download.")
    return path


def load_model(model_name: str):
    """Load a fresh YOLO instance.

    A new instance is created per processing job because Ultralytics keeps
    tracker state on the model object (``persist=True``); sharing one model
    between videos would leak track IDs across videos.
    """
    _configure_ultralytics()
    weights = resolve_weights(model_name)
    try:
        from ultralytics import YOLO

        return YOLO(str(weights))
    except Exception as exc:
        raise ModelWeightsMissingError(f"Failed to load model '{model_name}': {exc}") from exc
