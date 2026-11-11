"""Chunked result files.

Layout::

    storage/results/{job_id}/{model_id}/meta.json
    storage/results/{job_id}/{model_id}/chunk_00000.jsonl.gz   # frames with 0 <= t < 10 s
    storage/results/{job_id}/{model_id}/chunk_00001.jsonl.gz   # 10 <= t < 20 s
    storage/results/{job_id}/{model_id}/summary.json           # job-level outputs

Each line of a chunk is ``{"f": frame_index, "t": seconds, "d": {data_type: value}}``.
Chunking by time lets the overlay API load any time range without
decompressing the whole result.
"""

from __future__ import annotations

import gzip
import heapq
import json
import logging
import math
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.vision.base_model import ResultsReader

logger = logging.getLogger(__name__)

_CHUNK_FMT = "chunk_{:05d}.jsonl.gz"


def _dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), allow_nan=False)


class ModelResultWriter:
    def __init__(self, model_dir: Path, chunk_seconds: float) -> None:
        self.dir = model_dir
        self.chunk_seconds = chunk_seconds
        self.dir.mkdir(parents=True, exist_ok=True)
        self._chunk: int | None = None
        self._fh = None
        self.frames_written = 0

    def write(self, frame_index: int, timestamp: float, data: dict[str, Any]) -> None:
        chunk = int(timestamp // self.chunk_seconds)
        if chunk != self._chunk:
            self._close_chunk()
            self._chunk = chunk
            self._fh = gzip.open(self.dir / _CHUNK_FMT.format(chunk), "at", encoding="utf-8", compresslevel=5)
        self._fh.write(_dumps({"f": frame_index, "t": round(timestamp, 4), "d": data}) + "\n")
        self.frames_written += 1

    def _close_chunk(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def write_meta(self, meta: dict[str, Any]) -> None:
        (self.dir / "meta.json").write_text(_dumps(meta))

    def write_summary(self, summary: dict[str, Any]) -> None:
        (self.dir / "summary.json").write_text(_dumps(summary))

    def close(self) -> None:
        self._close_chunk()


class JobResultStore:
    """Read/write access to one job's results directory."""

    def __init__(self, job_dir: Path, chunk_seconds: float = 10.0) -> None:
        self.dir = job_dir
        self.chunk_seconds = chunk_seconds

    def writer(self, model_id: str) -> ModelResultWriter:
        return ModelResultWriter(self.dir / model_id, self.chunk_seconds)

    def delete(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    # --------------------------------------------------------------- reading
    def model_ids(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        return sorted(p.name for p in self.dir.iterdir() if p.is_dir())

    def meta(self, model_id: str) -> dict[str, Any]:
        path = self.dir / model_id / "meta.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def summary(self, model_id: str) -> dict[str, Any]:
        path = self.dir / model_id / "summary.json"
        return json.loads(path.read_text()) if path.is_file() else {}

    def _chunks(self, model_id: str) -> list[tuple[int, Path]]:
        d = self.dir / model_id
        if not d.is_dir():
            return []
        out = []
        for p in d.glob("chunk_*.jsonl.gz"):
            try:
                out.append((int(p.name[6:11]), p))
            except ValueError:
                continue
        return sorted(out)

    @staticmethod
    def _read_chunk(path: Path) -> Iterator[dict]:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        yield json.loads(line)
        except (EOFError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
            # A job interrupted mid-write can leave a truncated final chunk.
            logger.warning("Truncated result chunk %s: %s", path, exc)

    def iter_model(self, model_id: str, start: float = 0.0, end: float = math.inf) -> Iterator[dict]:
        first = int(start // self.chunk_seconds)
        last = math.inf if math.isinf(end) else int(end // self.chunk_seconds)
        for n, path in self._chunks(model_id):
            if n < first or n > last:
                continue
            for rec in self._read_chunk(path):
                if start <= rec["t"] <= end:
                    yield rec

    def iter_merged(self, model_ids: list[str], start: float = 0.0,
                    end: float = math.inf) -> Iterator[tuple[int, float, dict[str, Any]]]:
        """Merge several models' per-frame records by frame index."""
        streams = [self.iter_model(m, start, end) for m in model_ids]
        merged = heapq.merge(*streams, key=lambda r: r["f"])
        current_f: int | None = None
        current_t = 0.0
        data: dict[str, Any] = {}
        for rec in merged:
            if rec["f"] != current_f:
                if current_f is not None:
                    yield current_f, current_t, data
                current_f, current_t, data = rec["f"], rec["t"], {}
            data.update(rec["d"])
        if current_f is not None:
            yield current_f, current_t, data

    def reader(self, model_ids: list[str]) -> StoreResultsReader:
        return StoreResultsReader(self, model_ids)


class StoreResultsReader(ResultsReader):
    def __init__(self, store: JobResultStore, model_ids: list[str]) -> None:
        self.store = store
        self.model_ids = model_ids

    def iter_frames(self) -> Iterator[tuple[int, float, dict[str, Any]]]:
        return self.store.iter_merged(self.model_ids)

    def frame_count(self) -> int:
        counts = [self.store.meta(m).get("frames_written", 0) for m in self.model_ids]
        return max(counts) if counts else 0
