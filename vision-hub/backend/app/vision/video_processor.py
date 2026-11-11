"""Video scanning helpers: stream inspection, thumbnails and browser-playback copies.

Browsers reliably play H.264 in MP4/MOV only. Anything else (HEVC, AVI, MKV,
MPEG-4 Part 2…) gets an H.264 playback copy during scanning, so the canvas
overlay always has a playable video underneath it.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2

from app.config import settings
from app.core.exceptions import ProcessingError
from app.vision.video_io import ffmpeg_executable

logger = logging.getLogger(__name__)

_VIDEO_RE = re.compile(r"Stream #\d+:\d+[^:]*: Video: ([A-Za-z0-9_]+)")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+[^:]*: Audio: ([A-Za-z0-9_]+)")
_INPUT_RE = re.compile(r"Input #0, ([^,\s]+)")

BROWSER_CONTAINERS = {".mp4", ".mov"}
BROWSER_CODECS = {"h264"}


@dataclass
class StreamInfo:
    codec: str | None
    audio_codec: str | None
    container: str | None

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None


def inspect_streams(path: Path) -> StreamInfo:
    """Read codec names from ``ffmpeg -i`` (imageio-ffmpeg ships ffmpeg but not ffprobe)."""
    exe = ffmpeg_executable()
    if exe:
        try:
            out = subprocess.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, timeout=30)
            text = out.stderr.decode(errors="replace")
            v, a, c = _VIDEO_RE.search(text), _AUDIO_RE.search(text), _INPUT_RE.search(text)
            return StreamInfo(v.group(1).lower() if v else None, a.group(1).lower() if a else None,
                              c.group(1) if c else None)
        except Exception as exc:
            logger.warning("ffmpeg stream inspection failed: %s", exc)
    # Fallback: OpenCV FOURCC (no audio information).
    cap = cv2.VideoCapture(str(path))
    try:
        code = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        fourcc = "".join(chr((code >> 8 * i) & 0xFF) for i in range(4)).strip().lower() if code else None
    finally:
        cap.release()
    codec = {"avc1": "h264", "h264": "h264", "hev1": "hevc", "hvc1": "hevc"}.get(fourcc or "", fourcc)
    return StreamInfo(codec, None, None)


def needs_playback_copy(path: Path, info: StreamInfo) -> bool:
    return not (path.suffix.lower() in BROWSER_CONTAINERS and info.codec in BROWSER_CODECS)


def make_thumbnail(source: Path, out: Path, duration: float, width: int = 480) -> None:
    cap = cv2.VideoCapture(str(source))
    try:
        if duration and duration > 2:
            cap.set(cv2.CAP_PROP_POS_MSEC, min(duration * 0.1, 5.0) * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise ProcessingError("Could not read a frame for the thumbnail.")
    finally:
        cap.release()
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 85]):
        raise ProcessingError("Could not write the thumbnail.")


def transcode_for_playback(source: Path, out: Path, timeout: float = 3600) -> None:
    """Create a browser-friendly H.264/AAC MP4 copy (same resolution and frame rate)."""
    exe = ffmpeg_executable()
    if not exe:
        raise ProcessingError("FFmpeg is not available to create a browser playback copy.")
    tmp = out.with_suffix(".part.mp4")
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-c:v", "libx264", "-preset", settings.output_preset, "-crf", str(settings.output_crf),
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(tmp),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        tmp.unlink(missing_ok=True)
        raise ProcessingError("Creating the playback copy timed out.") from exc
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        err = result.stderr.decode(errors="replace")[-400:]
        raise ProcessingError(f"Creating the playback copy failed: {err}")
    tmp.replace(out)
