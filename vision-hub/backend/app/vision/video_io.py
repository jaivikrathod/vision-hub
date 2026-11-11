"""Video probing and writing.

Output is encoded as browser-friendly H.264 (yuv420p, faststart) by piping raw
frames into FFmpeg. FFmpeg is taken from the system PATH or, if absent, from
the bundled ``imageio-ffmpeg`` binary. If no FFmpeg is available an OpenCV
writer is used as a fallback (``avc1`` then ``mp4v``).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from app.config import settings
from app.core.exceptions import CorruptedVideoError, EmptyVideoError, ProcessingError

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    fps: float
    width: int
    height: int
    total_frames: int
    duration: float


def probe_video(path: Path) -> VideoMetadata:
    """Open a video with OpenCV, verify a frame decodes, and read its properties."""
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise CorruptedVideoError("The video could not be opened. It may be corrupted or use an unsupported codec.")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise EmptyVideoError("No frames could be decoded from this video. It may be empty or corrupted.")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        if not np.isfinite(fps) or fps <= 0 or fps > 1000:
            fps = 25.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        height, width = frame.shape[:2]
        duration = total / fps if total > 0 else 0.0
        return VideoMetadata(fps=float(fps), width=int(width), height=int(height),
                             total_frames=max(total, 0), duration=float(duration))
    finally:
        cap.release()


@lru_cache(maxsize=1)
def ffmpeg_executable() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


class FrameWriter:
    codec: str = "unknown"

    def write(self, frame: np.ndarray) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def abort(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class FfmpegPipeWriter(FrameWriter):
    codec = "h264"

    def __init__(self, path: Path, width: int, height: int, fps: float, exe: str) -> None:
        self.path = path
        self._log = tempfile.TemporaryFile(dir=settings.temp_dir)
        cmd = [
            exe, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6f}", "-i", "-",
            "-an",
            # yuv420p needs even dimensions.
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v", "libx264", "-preset", settings.output_preset, "-crf", str(settings.output_crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(path),
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log)
        self._closed = False

    def write(self, frame: np.ndarray) -> None:
        try:
            self._proc.stdin.write(np.ascontiguousarray(frame).data)
        except (BrokenPipeError, OSError) as exc:
            raise ProcessingError(f"Video encoder stopped unexpectedly: {self._stderr()}") from exc

    def _stderr(self) -> str:
        try:
            self._log.seek(0)
            return self._log.read().decode(errors="replace").strip()[-500:]
        except Exception:
            return ""

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        code = self._proc.wait()
        err = self._stderr()
        self._log.close()
        if code != 0:
            raise ProcessingError(f"FFmpeg encoding failed (exit {code}): {err}")

    def abort(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._proc.kill()
            self._proc.wait(timeout=5)
        except Exception:
            pass
        self._log.close()


class OpenCVWriter(FrameWriter):
    def __init__(self, path: Path, width: int, height: int, fps: float) -> None:
        self.path = path
        self._writer = None
        for fourcc in ("avc1", "mp4v"):
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc), fps, (width, height))
            if writer.isOpened():
                self._writer, self.codec = writer, fourcc
                break
            writer.release()
        if self._writer is None:
            raise ProcessingError("No compatible video encoder available (tried FFmpeg, avc1, mp4v).")
        logger.warning("FFmpeg unavailable; using OpenCV '%s' writer (may not play in all browsers)", self.codec)

    def write(self, frame: np.ndarray) -> None:
        self._writer.write(frame)

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


def open_writer(path: Path, width: int, height: int, fps: float) -> FrameWriter:
    exe = ffmpeg_executable()
    if exe:
        try:
            return FfmpegPipeWriter(path, width, height, fps, exe)
        except Exception as exc:
            logger.warning("FFmpeg writer failed to start (%s); falling back to OpenCV", exc)
    return OpenCVWriter(path, width, height, fps)


def mux_audio(video_path: Path, audio_source: Path, out_path: Path) -> bool:
    """Best effort: copy the original audio track into the annotated video."""
    exe = ffmpeg_executable()
    if not exe:
        return False
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-i", str(audio_source),
        "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart", str(out_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=600)
    except Exception as exc:
        logger.warning("Audio mux failed: %s", exc)
        return False
    if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        logger.warning("Audio mux failed: %s", result.stderr.decode(errors="replace")[-300:])
        out_path.unlink(missing_ok=True)
        return False
    return True
