"""Background analysis worker (separate process).

Run from ``backend/``::

    python -m app.workers.analysis_worker

The worker claims queued jobs from the SQLite queue one at a time, runs the
model executor, and persists results. A heartbeat thread keeps the job's
``heartbeat_at`` fresh (even during long model downloads), and writes
``storage/worker_status.json`` so the API can show whether the worker is up.
Jobs left ``processing`` by a dead worker are marked failed.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import socket
import threading
import time
from datetime import timedelta

from sqlalchemy import delete, insert, select, update

from app.config import settings
from app.core.database import run_migrations, session_scope, utcnow
from app.core.exceptions import AppError, ProcessingCancelled
from app.core.security import resolve_managed_path, to_relative
from app.db import (
    ActivitySegment,
    AnalysisJob,
    AnalysisJobModel,
    ExecutionStatus,
    FrameStat,
    JobStatus,
    ModelBenchmark,
    TrackedPerson,
    Video,
)
from app.vision import data_types as dt
from app.vision.annotator import OverlayOptions
from app.vision.model_executor import Callbacks, ExecutionResult, JobOptions, ModelExecutor, ModelRun
from app.vision.model_manager import ModelManager
from app.vision.model_registry import registry
from app.vision.pipeline_planner import plan_pipeline
from app.vision.result_store import JobResultStore
from app.vision.weights import configure_torch_threads, cuda_info, select_device
from app.workers.job_queue import JobQueue, make_worker_id, queue, write_worker_status

logger = logging.getLogger("app.worker")

INTERRUPTED = "The worker stopped while this analysis was running. Start it again."
MAX_FRAME_STAT_POINTS = 5000


class AnalysisWorker:
    def __init__(self, job_queue: JobQueue | None = None, manager: ModelManager | None = None) -> None:
        self.queue = job_queue or queue
        self.manager = manager or ModelManager()
        self.worker_id = make_worker_id()
        self.device = select_device()
        self.stop_event = threading.Event()
        self.current_job: int | None = None
        self._cancel_flag = False

    # ------------------------------------------------------------ lifecycle
    def run_forever(self) -> None:
        logger.info("Worker %s started (device=%s, torch threads=%d)", self.worker_id, self.device,
                    settings.torch_threads)
        hb = threading.Thread(target=self._heartbeat_loop, name="worker-heartbeat", daemon=True)
        hb.start()
        while not self.stop_event.is_set():
            try:
                self.recover_stale_jobs()
                job_id = self.queue.claim(self.worker_id)
            except Exception:
                logger.exception("Queue error; retrying")
                job_id = None
            if job_id is None:
                self.stop_event.wait(settings.worker_poll_seconds)
                continue
            self.run_job(job_id)
        self.manager.unload_all()
        logger.info("Worker stopped")

    def stop(self) -> None:
        self.stop_event.set()

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                job_id = self.current_job
                if job_id is not None:
                    self.queue.heartbeat(job_id, self.worker_id)
                cuda_ok, cuda_name = cuda_info()
                write_worker_status({
                    "worker_id": self.worker_id, "pid": os.getpid(), "device": self.device,
                    "cuda_available": cuda_ok, "cuda_device": cuda_name, "torch_threads": settings.torch_threads,
                    "loaded_models": self.manager.loaded_ids(), "current_job": job_id,
                })
            except Exception as exc:
                logger.debug("Heartbeat failed: %s", exc)
            self.stop_event.wait(settings.worker_heartbeat_seconds)

    # -------------------------------------------------------------- recovery
    def recover_stale_jobs(self) -> int:
        """Fail ``processing`` jobs whose worker is gone (dead PID on this host, or stale heartbeat)."""
        host = socket.gethostname()
        cutoff = utcnow() - timedelta(seconds=settings.worker_stale_seconds)
        failed = 0
        with session_scope() as db:
            jobs = db.scalars(select(AnalysisJob).where(AnalysisJob.status == JobStatus.PROCESSING.value)).all()
            for job in jobs:
                if job.worker_id == self.worker_id:
                    continue
                dead = False
                w_host, _, w_pid = (job.worker_id or "").rpartition(":")
                if w_host == host and w_pid.isdigit():
                    dead = not _pid_alive(int(w_pid))
                if dead or (job.heartbeat_at is not None and job.heartbeat_at < cutoff):
                    _mark_failed(db, job, INTERRUPTED)
                    failed += 1
        if failed:
            logger.warning("Marked %d interrupted job(s) as failed", failed)
        return failed

    # ------------------------------------------------------------------ jobs
    def _is_cancelled(self) -> bool:
        return self._cancel_flag

    def run_job(self, job_id: int) -> None:
        self.current_job = job_id
        self._cancel_flag = False
        store = JobResultStore(settings.results_dir / str(job_id), settings.result_chunk_seconds)
        try:
            with session_scope() as db:
                job = db.get(AnalysisJob, job_id)
                video = db.get(Video, job.video_id) if job else None
                if job is None or video is None:
                    return
                job.device = self.device
                selected = [m.model_id for m in job.models]
                configs = {m.model_id: m.configuration for m in job.models}
                auto = {m.model_id for m in job.models if m.auto_added}
                options = dict(job.options or {})
                source = resolve_managed_path(video.file_path)
                fps_hint = video.fps
            from app.services.analysis_service import measured_seconds_per_frame

            with session_scope() as db:
                spf = measured_seconds_per_frame(db, self.device)
            pipeline = plan_pipeline(selected, configs)
            for step in pipeline.steps:
                step.auto_added = step.model_id in auto
            overlay = OverlayOptions(**(options.get("overlay") or {}))
            job_options = JobOptions(frame_interval=int(options.get("frame_interval", 1)),
                                     render_video=bool(options.get("render_video", True)),
                                     overlay=overlay, seconds_per_frame=spf)
            store.delete()  # a previous partial run of this job, if any
            progress = _ProgressWriter(job_id, self)
            executor = ModelExecutor(
                job_id, source, pipeline, job_options, self.manager, store, self.device,
                Callbacks(on_progress=progress.on_progress, on_model_status=progress.on_model_status,
                          is_cancelled=self._is_cancelled),
                fps_hint=fps_hint,
            )
            logger.info("Job #%s started: %s", job_id, pipeline.model_ids)
            result = executor.run()
            self._persist(job_id, result, store, pipeline)
            logger.info("Job #%s completed in %.1fs", job_id, result.elapsed)
        except ProcessingCancelled as exc:
            store.delete()
            with session_scope() as db:
                job = db.get(AnalysisJob, job_id)
                if job is not None and self.stop_event.is_set() and not job.cancel_requested:
                    _mark_failed(db, job, INTERRUPTED)  # worker shutdown, not a user cancel
                elif job is not None:
                    _finish_models(db, job_id, ExecutionStatus.CANCELLED.value)
                    job.status = JobStatus.CANCELLED.value
                    job.current_stage = "Cancelled"
                    job.error_message = str(exc)
                    job.completed_at = utcnow()
            logger.info("Job #%s cancelled", job_id)
        except Exception as exc:
            message = exc.message if isinstance(exc, AppError) else f"Analysis failed: {exc}"
            if not isinstance(exc, AppError):
                logger.exception("Job #%s failed", job_id)
            else:
                logger.error("Job #%s failed: %s", job_id, message)
            store.delete()
            with session_scope() as db:
                job = db.get(AnalysisJob, job_id)
                if job is not None:
                    _mark_failed(db, job, message)
        finally:
            self.current_job = None
            for f in settings.temp_dir.glob(f"*-{job_id}-*.mp4"):
                f.unlink(missing_ok=True)

    def _persist(self, job_id: int, result: ExecutionResult, store: JobResultStore, pipeline) -> None:
        export_rel = None
        if result.annotated_video and result.annotated_video.is_file():
            export_dir = settings.exports_dir / str(job_id)
            export_dir.mkdir(parents=True, exist_ok=True)
            target = export_dir / "annotated.mp4"
            shutil.move(str(result.annotated_video), target)
            export_rel = to_relative(target)

        with session_scope() as db:
            job = db.get(AnalysisJob, job_id)
            for m in db.scalars(select(AnalysisJobModel).where(AnalysisJobModel.job_id == job_id)).all():
                run = result.runs.get(m.model_id)
                if run is None:
                    continue
                m.execution_status = run.status
                m.execution_time = round(run.seconds, 3)
                m.error_message = run.error
                m.weights_sha256 = run.weight_hashes
                m.result_path = to_relative(store.dir / m.model_id) if (store.dir / m.model_id).is_dir() else None

            # Clear rows of a previous attempt, then insert summaries.
            for table in (TrackedPerson, ActivitySegment, FrameStat):
                db.execute(delete(table).where(table.job_id == job_id))
            tracks = next(iter(result.outputs_of_type(dt.TRACK_SUMMARIES).values()), None)
            if tracks:
                db.execute(insert(TrackedPerson), [
                    {"job_id": job_id, "track_id": s["track_id"], "first_seen": s["first_seen"],
                     "last_seen": s["last_seen"], "frame_count": s["frame_count"],
                     "avg_confidence": s["avg_confidence"], "trajectory": s["trajectory"]} for s in tracks])
            seg_rows = [
                {"job_id": job_id, "model_id": model_id, "track_id": s["track_id"], "start_time": s["start"],
                 "end_time": s["end"], "label": s["label"], "confidence": s["confidence"], "method": s["method"]}
                for model_id, segs in result.outputs_of_type(dt.ACTIVITY_SEGMENTS).items() for s in segs
            ]
            if seg_rows:
                db.execute(insert(ActivitySegment), seg_rows)
            stats = result.frame_stats
            if len(stats) > MAX_FRAME_STAT_POINTS:
                step = len(stats) / MAX_FRAME_STAT_POINTS
                stats = [stats[int(i * step)] for i in range(MAX_FRAME_STAT_POINTS)]
            if stats:
                db.execute(insert(FrameStat), [
                    {"job_id": job_id, "frame_number": f, "timestamp": t, "people_count": c} for f, t, c in stats])

            counts = [c for _, _, c in result.frame_stats]
            job.summary = {
                "frames_decoded": result.frames_decoded,
                "frames_processed": result.frames_processed,
                "processing_seconds": round(result.elapsed, 2),
                "processing_fps": round(result.frames_decoded / result.elapsed, 2) if result.elapsed else None,
                "unique_people": len(tracks) if tracks is not None else None,
                "total_detections": result.detection_count,
                "average_people_per_frame": round(sum(counts) / len(counts), 3) if counts else None,
                "max_people_in_frame": max(counts) if counts else None,
                "posture_distribution": result.posture_counts,
                "coord_width": result.video.width, "coord_height": result.video.height,
                "fps": result.video.fps, "duration": result.video.duration,
                "failed_models": [m for m, r in result.runs.items() if r.status in ("failed", "skipped")],
            }
            job.annotated_video_path = export_rel
            job.status = JobStatus.COMPLETED.value
            job.progress = 100.0
            job.current_stage = "Completed" if not job.summary["failed_models"] else "Completed with errors"
            job.completed_at = utcnow()
            job.progress_detail = {**(job.progress_detail or {}), "eta_seconds": 0}
            self._update_benchmarks(db, result, pipeline)

    def _update_benchmarks(self, db, result: ExecutionResult, pipeline) -> None:
        """Store seconds per processed frame, normalised to each model's default configuration."""
        if not result.frames_processed:
            return
        for model_id, run in result.runs.items():
            if run.status != "completed":
                continue
            step = pipeline.step(model_id)
            cost = registry.get_class(model_id).relative_cost(step.config) or 1.0
            spf = run.seconds / result.frames_processed / cost
            version = registry.get_spec(model_id).version
            row = db.scalar(select(ModelBenchmark).where(
                ModelBenchmark.model_id == model_id, ModelBenchmark.model_version == version,
                ModelBenchmark.device == self.device))
            if row is None:
                db.add(ModelBenchmark(model_id=model_id, model_version=version, device=self.device,
                                      seconds_per_frame=spf, samples=1))
            else:  # exponential moving average: recent runs matter more
                row.seconds_per_frame = 0.6 * row.seconds_per_frame + 0.4 * spf
                row.samples += 1


class _ProgressWriter:
    """Throttled progress persistence; also picks up cancellation requests from the API."""

    def __init__(self, job_id: int, worker: AnalysisWorker) -> None:
        self.job_id = job_id
        self.worker = worker
        self._last = 0.0

    def on_progress(self, fraction: float, stage: str, detail: dict) -> None:
        now = time.monotonic()
        if now - self._last < settings.progress_db_interval_seconds:
            return
        self._last = now
        with session_scope() as db:
            db.execute(update(AnalysisJob).where(AnalysisJob.id == self.job_id).values(
                progress=round(fraction * 100, 2), current_stage=stage, progress_detail=detail,
                heartbeat_at=utcnow()))
            cancel = db.scalar(select(AnalysisJob.cancel_requested).where(AnalysisJob.id == self.job_id))
        if cancel:
            self.worker._cancel_flag = True

    def on_model_status(self, run: ModelRun) -> None:
        with session_scope() as db:
            db.execute(update(AnalysisJobModel).where(
                AnalysisJobModel.job_id == self.job_id, AnalysisJobModel.model_id == run.model_id
            ).values(execution_status=run.status, error_message=run.error,
                     execution_time=round(run.seconds, 3)))


def _finish_models(db, job_id: int, status: str) -> None:
    db.execute(update(AnalysisJobModel).where(
        AnalysisJobModel.job_id == job_id,
        AnalysisJobModel.execution_status.in_([ExecutionStatus.PENDING.value, ExecutionStatus.RUNNING.value])
    ).values(execution_status=status))


def _mark_failed(db, job: AnalysisJob, message: str) -> None:
    _finish_models(db, job.id, ExecutionStatus.FAILED.value)
    job.status = JobStatus.FAILED.value
    job.current_stage = "Failed"
    job.error_message = message
    job.completed_at = utcnow()
    shutil.rmtree(settings.results_dir / str(job.id), ignore_errors=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def main() -> None:
    logging.basicConfig(level=settings.log_level.upper(),
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    settings.ensure_directories()
    run_migrations()
    configure_torch_threads()
    with session_scope() as db:
        registry.sync_to_db(db)
    worker = AnalysisWorker()

    def _stop(signum, _frame):
        logger.info("Received signal %s; finishing the current frame and stopping…", signum)
        worker._cancel_flag = True  # interrupts the running job; it is recorded as interrupted
        worker.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
