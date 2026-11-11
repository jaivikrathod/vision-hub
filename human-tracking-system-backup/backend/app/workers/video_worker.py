"""In-process background worker with a bounded job queue.

* A fixed number of worker threads (``MAX_CONCURRENT_JOBS``, default 1) limits
  CPU/RAM usage; extra jobs wait in the queue with status ``queued``.
* A task registry keeps live progress in memory for the progress/SSE APIs;
  progress is also persisted to SQLite periodically.
* No external infrastructure (Celery/Redis/…) is needed.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from sqlalchemy import select, update

from app.config import settings
from app.core.database import session_scope
from app.models import DetectionSession, ProcessingStatus, Video
from app.services.video_processing_service import ProcessingOptions, ProgressReporter, VideoProcessor
from app.services.video_service import clear_results

logger = logging.getLogger(__name__)

TERMINAL = {ProcessingStatus.COMPLETED.value, ProcessingStatus.FAILED.value, ProcessingStatus.CANCELLED.value}


@dataclass
class TaskState:
    video_id: int
    session_id: int
    options: ProcessingOptions
    status: str = ProcessingStatus.QUEUED.value
    percentage: float = 0.0
    frames_processed: int = 0
    total_frames: int | None = None
    detected_people: int = 0
    people_in_frame: int = 0
    processing_fps: float | None = None
    eta_seconds: float | None = None
    elapsed_seconds: float | None = None
    device: str | None = None
    message: str | None = "Waiting in queue…"
    version: int = 0
    cancel_event: threading.Event = field(default_factory=threading.Event)
    shutdown: bool = False

    def apply(self, **values) -> None:
        for key, value in values.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.version += 1

    def snapshot(self) -> dict:
        return {
            "video_id": self.video_id, "status": self.status, "percentage": self.percentage,
            "frames_processed": self.frames_processed, "total_frames": self.total_frames,
            "detected_people": self.detected_people, "people_in_frame": self.people_in_frame,
            "processing_fps": self.processing_fps, "eta_seconds": self.eta_seconds,
            "elapsed_seconds": self.elapsed_seconds, "device": self.device, "message": self.message,
        }


class VideoWorker:
    def __init__(self, concurrency: int) -> None:
        self.concurrency = max(1, concurrency)
        self._queue: queue.Queue[TaskState | None] = queue.Queue()
        self._tasks: dict[int, TaskState] = {}
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._running = False

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for i in range(self.concurrency):
            t = threading.Thread(target=self._loop, name=f"video-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)
        logger.info("Video worker started with %d thread(s)", self.concurrency)

    def stop(self, timeout: float = 15.0) -> None:
        if not self._running:
            return
        self._running = False
        with self._lock:
            for task in self._tasks.values():
                if task.status not in TERMINAL:
                    task.shutdown = True
                    task.cancel_event.set()
        for _ in self._threads:
            self._queue.put(None)
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))
        self._threads.clear()
        logger.info("Video worker stopped")

    # -------------------------------------------------------------------- API
    def submit(self, video_id: int, session_id: int, options: ProcessingOptions) -> TaskState:
        task = TaskState(video_id=video_id, session_id=session_id, options=options)
        with self._lock:
            existing = self._tasks.get(video_id)
            if existing and existing.status not in TERMINAL:
                raise RuntimeError("Video is already queued or processing")
            self._tasks[video_id] = task
        self._queue.put(task)
        return task

    def cancel(self, video_id: int) -> bool:
        with self._lock:
            task = self._tasks.get(video_id)
        if task is None or task.status in TERMINAL:
            return False
        task.cancel_event.set()
        task.apply(message="Cancelling…")
        return True

    def get(self, video_id: int) -> TaskState | None:
        with self._lock:
            return self._tasks.get(video_id)

    def is_active(self, video_id: int) -> bool:
        task = self.get(video_id)
        return task is not None and task.status not in TERMINAL

    def queue_size(self) -> int:
        return self._queue.qsize()

    # ----------------------------------------------------------------- worker
    def _loop(self) -> None:
        while True:
            task = self._queue.get()
            try:
                if task is None:
                    return
                self._run(task)
            except Exception:
                logger.exception("Worker crashed while running video #%s", getattr(task, "video_id", "?"))
            finally:
                self._queue.task_done()

    def _run(self, task: TaskState) -> None:
        def is_cancelled() -> bool:
            return task.cancel_event.is_set()

        def on_progress(**values) -> None:
            if task.shutdown and values.get("status") == ProcessingStatus.CANCELLED.value:
                values["status"] = ProcessingStatus.FAILED.value
            task.apply(**values)

        reporter = ProgressReporter(on_progress=on_progress, is_cancelled=is_cancelled)
        if not task.shutdown:
            task.apply(status=ProcessingStatus.PROCESSING.value, message="Starting…")
        VideoProcessor(task.video_id, task.session_id, task.options, reporter).run()

        if task.shutdown:
            # Application stopped mid-processing: record it as interrupted, not user-cancelled.
            mark_interrupted([task.video_id])
            task.apply(status=ProcessingStatus.FAILED.value, message=INTERRUPTED_MESSAGE)


INTERRUPTED_MESSAGE = "Processing was interrupted because the application stopped. Start processing again."


def mark_interrupted(video_ids: list[int] | None = None) -> int:
    """Mark queued/processing videos as failed (used at startup and shutdown)."""
    active = [s.value for s in ProcessingStatus.active()] + [ProcessingStatus.CANCELLED.value]
    with session_scope() as db:
        q = select(Video).where(Video.processing_status.in_(active if video_ids else
                                                            [s.value for s in ProcessingStatus.active()]))
        if video_ids:
            q = q.where(Video.id.in_(video_ids))
        videos = db.scalars(q).all()
        for v in videos:
            # Partial results of an interrupted run are discarded.
            clear_results(db, v.id)
            v.processing_status = ProcessingStatus.FAILED.value
            v.processing_percentage = 0.0
            v.frames_processed = 0
            v.total_unique_persons = 0
            v.error_message = INTERRUPTED_MESSAGE
        ids = [v.id for v in videos]
        if ids:
            db.execute(
                update(DetectionSession)
                .where(DetectionSession.video_id.in_(ids),
                       DetectionSession.status.in_([s.value for s in ProcessingStatus.active()] +
                                                   [ProcessingStatus.CANCELLED.value]))
                .values(status="interrupted")
            )
    if ids:
        logger.warning("Marked %d interrupted video(s) as failed: %s", len(ids), ids)
    return len(ids)


worker = VideoWorker(settings.max_concurrent_jobs)
