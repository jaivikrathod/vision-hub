"""Video processing engine: decode → detect → track → annotate → encode → persist.

Frames are streamed one at a time; the whole video is never held in memory.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import cv2
from sqlalchemy import insert, update

from app.config import settings
from app.core.database import SessionLocal
from app.core.exceptions import AppError, CorruptedVideoError, EmptyVideoError, ProcessingCancelled
from app.core.security import resolve_managed_path, sanitize_display_name, to_relative
from app.models import DetectionEvent, DetectionSession, ProcessingStatus, TrackedPerson, Video
from app.services import video_service
from app.services.detection_service import load_model, select_device
from app.services.tracking_service import PersonDetection, PersonTracker
from app.vision.annotator import FrameAnnotator, VisualizationSettings
from app.vision.video_io import mux_audio, open_writer

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Naive UTC timestamp (stored consistently with SQL server defaults)."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class _TrackStats:
    db_id: int
    first_frame: int
    last_frame: int
    first_ts: float
    last_ts: float
    count: int = 0
    conf_sum: float = 0.0


@dataclass
class ProcessingOptions:
    model_name: str
    confidence: float
    frame_skip: int
    show_boxes: bool = True
    show_ids: bool = True
    show_confidence: bool = False

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class ProgressReporter:
    """Interface the engine uses to report progress and check cancellation."""

    on_progress: callable = field(default=lambda **_: None)
    is_cancelled: callable = field(default=lambda: False)


class VideoProcessor:
    def __init__(self, video_id: int, session_id: int, options: ProcessingOptions, reporter: ProgressReporter):
        self.video_id = video_id
        self.session_id = session_id
        self.options = options
        self.reporter = reporter
        self.db = SessionLocal()
        self._tracks: dict[int, _TrackStats] = {}
        self._events: list[dict] = []
        self._total_detections = 0
        self._tmp_files: list[Path] = []

    # ------------------------------------------------------------------ public
    def run(self) -> None:
        started = time.monotonic()
        try:
            self._process(started)
        except ProcessingCancelled as exc:
            self._finish_unsuccessful(ProcessingStatus.CANCELLED, str(exc) or "Processing was cancelled.", started)
        except AppError as exc:
            logger.error("Processing video #%s failed: %s", self.video_id, exc.message)
            self._finish_unsuccessful(ProcessingStatus.FAILED, exc.message, started)
        except Exception as exc:
            logger.exception("Processing video #%s failed", self.video_id)
            self._finish_unsuccessful(ProcessingStatus.FAILED, f"Processing failed: {exc}", started)
        finally:
            for f in self._tmp_files:
                f.unlink(missing_ok=True)
            self.db.close()

    # ----------------------------------------------------------------- pipeline
    def _process(self, started: float) -> None:
        db = self.db
        video = db.get(Video, self.video_id)
        session = db.get(DetectionSession, self.session_id)
        if video is None or session is None:
            raise AppError("Video or detection session no longer exists.")
        if self.reporter.is_cancelled():
            raise ProcessingCancelled("Processing was cancelled before it started.")

        # Reset previous results (reprocessing).
        video_service.clear_results(db, self.video_id)
        old_output = video.processed_video_path
        video.processed_video_path = None
        video.processing_status = ProcessingStatus.PROCESSING.value
        video.processing_percentage = 0.0
        video.frames_processed = 0
        video.total_unique_persons = 0
        video.processing_time = None
        video.error_message = None
        session.status = ProcessingStatus.PROCESSING.value
        session.processing_started_at = _utcnow()
        db.commit()
        video_service.remove_file(old_output)

        source = resolve_managed_path(video.original_video_path)
        if not source.is_file():
            raise AppError("The original video file is missing from local storage.")
        video_service.ensure_disk_space(settings.processed_dir, video.file_size)

        device = select_device()
        session.device = device
        db.commit()
        self.reporter.on_progress(status=ProcessingStatus.PROCESSING.value, device=device,
                                  message=f"Loading {self.options.model_name} on {device}…")
        model = load_model(self.options.model_name)
        tracker = PersonTracker(model, confidence=self.options.confidence, device=device)

        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise CorruptedVideoError("The video could not be opened for processing.")
        writer = None
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or video.fps or 25.0
            if fps <= 0 or fps > 1000:
                fps = video.fps or 25.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or video.total_frames or 0)
            stride = self.options.frame_skip + 1

            annotator: FrameAnnotator | None = None
            tmp_out = settings.temp_dir / f"render-{uuid.uuid4().hex}.mp4"
            self._tmp_files.append(tmp_out)

            frame_idx = 0
            last_dets: list[PersonDetection] = []
            last_report = 0.0
            last_db = time.monotonic()
            self.reporter.on_progress(message="Processing frames…", total_frames=total)

            while True:
                if self.reporter.is_cancelled():
                    raise ProcessingCancelled("Processing was cancelled by the user.")
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = open_writer(tmp_out, w, h, fps)
                    annotator = FrameAnnotator(
                        VisualizationSettings(self.options.show_boxes, self.options.show_ids,
                                              self.options.show_confidence), w, h)

                if frame_idx % stride == 0:
                    last_dets = tracker.update(frame)
                    self._record(frame_idx, frame_idx / fps, last_dets)
                # Skipped frames reuse the last known boxes so the output keeps full length/FPS.
                annotator.draw(frame, last_dets)
                writer.write(frame)
                frame_idx += 1

                now = time.monotonic()
                if now - last_report >= 0.25:
                    last_report = now
                    self._report(frame_idx, total, started, len(last_dets))
                if now - last_db >= settings.progress_db_interval_seconds:
                    last_db = now
                    self._persist_progress(video, frame_idx, total)
        except BaseException:
            if writer is not None:
                writer.abort()
            raise
        finally:
            cap.release()

        if frame_idx == 0 or writer is None:
            raise EmptyVideoError("No frames could be decoded from this video.")
        if total and frame_idx < total * 0.9:
            logger.warning("Video #%s: decoded %d of %d reported frames (stream may be truncated)",
                           self.video_id, frame_idx, total)

        self.reporter.on_progress(message="Finalizing video…", percentage=99.0)
        writer.close()
        self._flush_events()

        # Move the encoded file into processed/, adding the original audio if possible.
        stem = Path(video.stored_filename).stem
        final_path = settings.processed_dir / f"{stem}_tracked.mp4"
        if not (settings.keep_audio and mux_audio(tmp_out, source, final_path)):
            shutil.move(str(tmp_out), final_path)

        elapsed = time.monotonic() - started
        self._finalize_tracks()
        unique = len(self._tracks)
        avg_fps = frame_idx / elapsed if elapsed > 0 else None

        video.processed_video_path = to_relative(final_path)
        video.processing_status = ProcessingStatus.COMPLETED.value
        video.processing_percentage = 100.0
        video.frames_processed = frame_idx
        video.total_frames = frame_idx
        video.duration = frame_idx / fps
        video.total_unique_persons = unique
        video.processing_time = elapsed
        session.status = ProcessingStatus.COMPLETED.value
        session.total_detections = self._total_detections
        session.total_unique_persons = unique
        session.total_frames_processed = frame_idx
        session.average_processing_fps = avg_fps
        session.processing_completed_at = _utcnow()
        self.db.commit()

        self.reporter.on_progress(status=ProcessingStatus.COMPLETED.value, percentage=100.0,
                                  frames_processed=frame_idx, total_frames=frame_idx,
                                  detected_people=unique, eta_seconds=0.0, message="Completed",
                                  processing_fps=avg_fps)
        logger.info("Video #%s processed: %d frames, %d people, %.1fs (%.1f FPS)",
                    self.video_id, frame_idx, unique, elapsed, avg_fps or 0)

    # ----------------------------------------------------------------- helpers
    def _record(self, frame_idx: int, ts: float, dets: list[PersonDetection]) -> None:
        for d in dets:
            stats = self._tracks.get(d.track_id)
            if stats is None:
                person = TrackedPerson(
                    video_id=self.video_id, tracking_id=d.track_id,
                    first_detected_frame=frame_idx, last_detected_frame=frame_idx,
                    first_detected_timestamp=round(ts, 4), last_detected_timestamp=round(ts, 4),
                    total_detected_frames=0, average_confidence=0.0,
                )
                self.db.add(person)
                self.db.flush()
                stats = _TrackStats(person.id, frame_idx, frame_idx, ts, ts)
                self._tracks[d.track_id] = stats
            stats.last_frame, stats.last_ts = frame_idx, ts
            stats.count += 1
            stats.conf_sum += d.confidence
            self._events.append({
                "video_id": self.video_id, "tracked_person_id": stats.db_id,
                "frame_number": frame_idx, "timestamp_seconds": round(ts, 4),
                "x1": round(d.x1, 1), "y1": round(d.y1, 1), "x2": round(d.x2, 1), "y2": round(d.y2, 1),
                "confidence": round(d.confidence, 4),
            })
            self._total_detections += 1
        if len(self._events) >= settings.event_batch_size:
            self._flush_events()

    def _flush_events(self) -> None:
        if self._events:
            self.db.execute(insert(DetectionEvent), self._events)
            self._events.clear()
        self.db.commit()

    def _finalize_tracks(self) -> None:
        if not self._tracks:
            return
        self.db.execute(update(TrackedPerson), [
            {
                "id": s.db_id,
                "last_detected_frame": s.last_frame,
                "last_detected_timestamp": round(s.last_ts, 4),
                "total_detected_frames": s.count,
                "average_confidence": round(s.conf_sum / s.count, 4) if s.count else 0.0,
            }
            for s in self._tracks.values()
        ])

    def _report(self, frame_idx: int, total: int, started: float, in_frame: int) -> None:
        elapsed = time.monotonic() - started
        fps = frame_idx / elapsed if elapsed > 0 else None
        pct = min(99.0, frame_idx / total * 100) if total else 0.0
        eta = (total - frame_idx) / fps if (fps and total and total > frame_idx) else None
        self.reporter.on_progress(
            frames_processed=frame_idx, total_frames=total or None, percentage=round(pct, 2),
            detected_people=len(self._tracks), people_in_frame=in_frame,
            processing_fps=round(fps, 2) if fps else None,
            eta_seconds=round(eta, 1) if eta is not None else None, elapsed_seconds=round(elapsed, 1),
        )

    def _persist_progress(self, video: Video, frame_idx: int, total: int) -> None:
        video.frames_processed = frame_idx
        video.processing_percentage = round(min(99.0, frame_idx / total * 100), 2) if total else 0.0
        video.total_unique_persons = len(self._tracks)
        self._flush_events()

    def _finish_unsuccessful(self, status: ProcessingStatus, message: str, started: float) -> None:
        try:
            self.db.rollback()
            video_service.clear_results(self.db, self.video_id)
            video = self.db.get(Video, self.video_id)
            session = self.db.get(DetectionSession, self.session_id)
            if video is not None:
                video_service.remove_file(video.processed_video_path)
                video.processed_video_path = None
                video.processing_status = status.value
                video.processing_percentage = 0.0
                video.frames_processed = 0
                video.total_unique_persons = 0
                video.processing_time = time.monotonic() - started
                video.error_message = message
            if session is not None:
                session.status = status.value
                session.processing_completed_at = _utcnow()
            self.db.commit()
        except Exception:
            logger.exception("Could not record final status for video #%s", self.video_id)
            self.db.rollback()
        self.reporter.on_progress(status=status.value, message=message)


def download_name(video: Video) -> str:
    stem = Path(sanitize_display_name(video.original_filename)).stem
    return f"{stem}_tracked.mp4"
