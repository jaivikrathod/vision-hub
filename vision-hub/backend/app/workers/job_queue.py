"""Job queue abstraction.

The default implementation stores the queue in the ``analysis_jobs`` table
(status ``queued``) and claims jobs atomically with ``UPDATE … RETURNING``, so
several worker processes could safely share one SQLite file. To scale out
later, implement :class:`JobQueue` on Redis/Celery; the executor and API don't
change.
"""

from __future__ import annotations

import json
import os
import socket
import time
from abc import ABC, abstractmethod
from pathlib import Path

from sqlalchemy import and_, func, select, update

from app.config import settings
from app.core.database import session_scope, utcnow
from app.db import AnalysisJob, JobStatus


def make_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


class JobQueue(ABC):
    @abstractmethod
    def enqueue(self, job_id: int) -> None:
        """Make a job available to workers (the job row already exists with status ``queued``)."""

    @abstractmethod
    def claim(self, worker_id: str) -> int | None:
        """Atomically take the oldest queued job, or return ``None``."""

    @abstractmethod
    def heartbeat(self, job_id: int, worker_id: str) -> None:
        """Signal that the worker running ``job_id`` is alive."""

    @abstractmethod
    def position(self, job_id: int) -> int | None:
        """1-based position among queued jobs, or ``None`` if not queued."""


class SqliteJobQueue(JobQueue):
    def enqueue(self, job_id: int) -> None:
        return None  # the row itself is the queue entry

    def claim(self, worker_id: str) -> int | None:
        now = utcnow()
        oldest = select(AnalysisJob.id).where(AnalysisJob.status == JobStatus.QUEUED.value) \
            .order_by(AnalysisJob.id).limit(1).scalar_subquery()
        stmt = (
            update(AnalysisJob)
            .where(and_(AnalysisJob.id == oldest, AnalysisJob.status == JobStatus.QUEUED.value))
            .values(status=JobStatus.PROCESSING.value, worker_id=worker_id, started_at=now,
                    heartbeat_at=now, progress=0.0, current_stage="Starting")
            .returning(AnalysisJob.id)
        )
        with session_scope() as db:
            row = db.execute(stmt).first()
        return int(row[0]) if row else None

    def heartbeat(self, job_id: int, worker_id: str) -> None:
        with session_scope() as db:
            db.execute(update(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.worker_id == worker_id)
                       .values(heartbeat_at=utcnow()))

    def position(self, job_id: int) -> int | None:
        with session_scope() as db:
            job = db.get(AnalysisJob, job_id)
            if job is None or job.status != JobStatus.QUEUED.value:
                return None
            ahead = db.scalar(select(func.count(AnalysisJob.id)).where(
                AnalysisJob.status == JobStatus.QUEUED.value, AnalysisJob.id < job_id)) or 0
            return ahead + 1


queue: JobQueue = SqliteJobQueue()


# ------------------------------------------------------------ worker status
def worker_status_path() -> Path:
    return settings.storage_dir / "worker_status.json"


def write_worker_status(data: dict) -> None:
    path = worker_status_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "updated_at": time.time()}))
    tmp.replace(path)


def read_worker_status() -> dict:
    """Last status written by the worker process; ``alive`` is false if it is stale or missing."""
    path = worker_status_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"alive": False}
    data["alive"] = time.time() - float(data.get("updated_at", 0)) < max(10.0, settings.worker_heartbeat_seconds * 5)
    return data
