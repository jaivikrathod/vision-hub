"""File-safety helpers: extension/content validation and path confinement."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app.config import BACKEND_DIR, settings
from app.core.exceptions import AppError, UnsupportedFormatError

# Container signatures ("magic bytes").
_EBML_MAGIC = b"\x1a\x45\xdf\xa3"  # Matroska / WebM
_RIFF_MAGIC = b"RIFF"


def normalize_extension(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def validate_extension(filename: str) -> str:
    ext = normalize_extension(filename)
    if ext not in settings.allowed_extensions:
        allowed = ", ".join(e.lstrip(".").upper() for e in settings.allowed_extensions)
        raise UnsupportedFormatError(
            f"Unsupported file type '{ext or 'none'}'. Supported formats: {allowed}."
        )
    return ext


def sniff_container(header: bytes) -> str | None:
    """Identify the video container from the first bytes of a file."""
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12]
        return "mov" if brand == b"qt  " else "mp4"
    if len(header) >= 12 and header[:4] == _RIFF_MAGIC and header[8:12] == b"AVI ":
        return "avi"
    if header[:4] == _EBML_MAGIC:
        return "mkv"
    # Some QuickTime files start with other atoms (moov/mdat/wide/free).
    if len(header) >= 8 and header[4:8] in (b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"):
        return "mov"
    return None


_COMPATIBLE = {
    ".mp4": {"mp4", "mov"},
    ".mov": {"mov", "mp4"},
    ".avi": {"avi"},
    ".mkv": {"mkv"},
}


def validate_content(ext: str, header: bytes) -> None:
    """Ensure the file content is really a video container matching its extension."""
    kind = sniff_container(header)
    if kind is None:
        raise UnsupportedFormatError("The file content is not a recognised video container.")
    if kind not in _COMPATIBLE.get(ext, set()):
        raise UnsupportedFormatError(
            f"File extension '{ext}' does not match its content (detected {kind.upper()})."
        )


def generate_stored_filename(ext: str) -> str:
    return f"{uuid.uuid4().hex}{ext}"


_SAFE_DISPLAY = re.compile(r"[^A-Za-z0-9._ -]+")


def sanitize_display_name(filename: str, max_len: int = 200) -> str:
    """Name safe to show and to use in Content-Disposition headers."""
    name = Path(filename or "video").name
    name = _SAFE_DISPLAY.sub("_", name).strip(" .") or "video"
    return name[:max_len]


def to_relative(path: Path) -> str:
    """Store paths relative to backend/ so the database is portable."""
    try:
        return str(path.resolve().relative_to(BACKEND_DIR))
    except ValueError:
        return str(path.resolve())


def resolve_managed_path(stored: str | None) -> Path:
    """Resolve a stored path and refuse anything outside managed directories."""
    if not stored:
        raise AppError("File is not available.")
    path = Path(stored)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path = path.resolve()
    if not any(path.is_relative_to(d.resolve()) for d in settings.managed_dirs):
        raise AppError("Access to this file is not allowed.")
    return path
