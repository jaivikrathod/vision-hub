"""Device selection, weight download/verification and SHA-256 recording.

Ultralytics doesn't publish official hashes, so the SHA-256 of every weight
artifact is computed on first download (or first use) and stored next to it in
``<name>.sha256``. Jobs record these hashes for reproducibility.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.core.exceptions import ModelWeightsMissingError
from app.vision.base_model import WeightInfo

logger = logging.getLogger(__name__)

_download_lock = threading.Lock()
_ultralytics_configured = False


# ------------------------------------------------------------------- device
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


def configure_torch_threads() -> None:
    try:
        import torch

        torch.set_num_threads(max(1, settings.torch_threads))
        logger.info("PyTorch using %d CPU thread(s)", torch.get_num_threads())
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not set PyTorch threads: %s", exc)


def configure_ultralytics() -> None:
    """Privacy: make sure Ultralytics never sends usage analytics."""
    global _ultralytics_configured
    if _ultralytics_configured:
        return
    try:
        from ultralytics import settings as yolo_settings

        if yolo_settings.get("sync", False):
            yolo_settings.update({"sync": False})
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not update Ultralytics settings: %s", exc)
    try:
        from ultralytics.utils import events as yolo_events

        yolo_events.events.enabled = False
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not disable Ultralytics events: %s", exc)
    _ultralytics_configured = True


# ------------------------------------------------------------------ weights
def weight_path(info: WeightInfo) -> Path:
    return settings.model_weights_dir / info.name


def _hf_snapshot_present(path: Path) -> bool:
    return (path / "config.json").is_file() and any(
        (path / f).is_file() for f in ("model.safetensors", "pytorch_model.bin")
    )


def is_present(info: WeightInfo) -> bool:
    path = weight_path(info)
    if info.kind == "hf_snapshot":
        return _hf_snapshot_present(path)
    return path.is_file() and path.stat().st_size > 0


def ensure_weights(info: WeightInfo) -> Path:
    """Return the local weight path, downloading it once if allowed."""
    path = weight_path(info)
    if is_present(info):
        return path
    if not settings.allow_model_download:
        raise ModelWeightsMissingError(
            f"Model weights '{info.name}' not found in model_weights/. "
            "Run `python scripts/download_weights.py` or set ALLOW_MODEL_DOWNLOAD=true."
        )
    with _download_lock:
        if is_present(info):
            return path
        size = f" (~{info.size_mb:.0f} MB)" if info.size_mb else ""
        logger.info("Downloading weights %s%s (one-time)…", info.name, size)
        settings.model_weights_dir.mkdir(parents=True, exist_ok=True)
        try:
            if info.kind == "hf_snapshot":
                from huggingface_hub import snapshot_download

                snapshot_download(
                    repo_id=info.source, local_dir=str(path),
                    allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors", "merges.txt", "vocab.*"],
                )
            else:
                configure_ultralytics()
                from ultralytics.utils.downloads import attempt_download_asset

                attempt_download_asset(str(path))
        except Exception as exc:
            raise ModelWeightsMissingError(f"Could not download weights '{info.name}': {exc}") from exc
        if not is_present(info):
            raise ModelWeightsMissingError(f"Download of '{info.name}' did not produce usable weights.")
        sha256_of(info)  # record the hash right after download
        return path


def _main_file(info: WeightInfo) -> Path:
    path = weight_path(info)
    if info.kind == "hf_snapshot":
        for name in ("model.safetensors", "pytorch_model.bin"):
            if (path / name).is_file():
                return path / name
    return path


def sha256_of(info: WeightInfo) -> str | None:
    """SHA-256 of the main weight file, cached in a ``.sha256`` side file."""
    if not is_present(info):
        return None
    main = _main_file(info)
    side = main.with_name(main.name + ".sha256")
    try:
        if side.is_file() and side.stat().st_mtime >= main.stat().st_mtime:
            return side.read_text().strip()
    except OSError:
        pass
    h = hashlib.sha256()
    with main.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    digest = h.hexdigest()
    try:
        side.write_text(digest + "\n")
    except OSError:
        logger.warning("Could not write %s", side)
    return digest
