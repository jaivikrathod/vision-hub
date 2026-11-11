"""Model executor: runs a planned pipeline over one video.

Stages:

1. **Load** the pipeline's models through the model manager.
2. **Single decode pass**: every sampled frame goes to all ``frame`` and ``clip``
   models in dependency order; each model sees this frame's earlier outputs in
   ``upstream``. Per-frame outputs are written to chunked result files.
3. **Finish**: ``frame``/``clip`` models return job-level outputs (track
   summaries, clip-based activities).
4. **Post models** run over the stored results.
5. **Render** (optional): a second decode pass draws the stored results onto
   every frame and encodes an H.264 MP4. Skipped frames hold the last result.

A failing model marks itself failed and its dependents skipped; independent
models still finish. The executor never touches the database: it returns an
:class:`ExecutionResult` that the worker persists.
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.exceptions import AppError, EmptyVideoError, ProcessingCancelled, ProcessingError
from app.vision import data_types as dt
from app.vision.annotator import ActivityLookup, FrameAnnotator, OverlayOptions, merge_persons
from app.vision.base_model import BaseVisionModel, FrameData, JobContext, VideoInfo
from app.vision.frame_extractor import FrameExtractor, processing_size
from app.vision.model_manager import ModelManager
from app.vision.pipeline_planner import Pipeline, PipelineStep
from app.vision.result_store import JobResultStore
from app.vision.video_io import mux_audio, open_writer

logger = logging.getLogger(__name__)


@dataclass
class JobOptions:
    frame_interval: int = 1
    render_video: bool = True
    overlay: OverlayOptions = field(default_factory=OverlayOptions)
    # Expected seconds per processed frame for each model (from benchmarks), used to
    # weight progress stages so the progress bar and ETA move evenly.
    seconds_per_frame: dict[str, float] = field(default_factory=dict)


# Rough per-frame costs of non-model work at 1080p on a laptop CPU (scaled by pixel count).
DECODE_SECONDS_PER_FRAME = 0.004
RENDER_SECONDS_PER_FRAME = 0.025
LOAD_SECONDS = 2.0


def _relative_cost(step: PipelineStep) -> float:
    from app.vision.model_registry import registry

    try:
        return float(registry.get_class(step.model_id).relative_cost(step.config))
    except Exception:
        return 1.0


def estimate_stages(pipeline: Pipeline, total_frames: int, frame_interval: int, width: int, height: int,
                    render_video: bool, seconds_per_frame: dict[str, float]) -> dict[str, float]:
    """Expected seconds per stage. Model costs come from measured benchmarks when available."""
    pixels = (width * height) / (1920 * 1080) if width and height else 1.0
    processed = total_frames / max(1, frame_interval)

    def cost(kinds: tuple[str, ...]) -> float:
        # Benchmarks are normalised to each model's default config; scale by this config's cost.
        return sum(seconds_per_frame.get(s.model_id, s.spec.default_seconds_per_frame)
                   * _relative_cost(s) for s in pipeline.steps if s.spec.kind in kinds)

    has_post = any(s.spec.kind == "post" for s in pipeline.steps)
    return {
        "load": LOAD_SECONDS * sum(1 for s in pipeline.steps if s.spec.neural) + 0.5,
        "decode": processed * cost(("frame", "clip")) + total_frames * DECODE_SECONDS_PER_FRAME * pixels,
        "post": processed * cost(("post",)) + (0.5 if has_post else 0.0),
        "render": total_frames * RENDER_SECONDS_PER_FRAME * pixels if render_video else 0.0,
    }


@dataclass
class ModelRun:
    model_id: str
    status: str = "pending"          # pending | running | completed | failed | skipped | cancelled
    seconds: float = 0.0
    error: str | None = None
    weight_hashes: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)   # job-level outputs

    @property
    def ok(self) -> bool:
        return self.status in ("pending", "running", "completed")


@dataclass
class ExecutionResult:
    runs: dict[str, ModelRun]
    frames_decoded: int
    frames_processed: int
    video: VideoInfo
    frame_stats: list[tuple[int, float, int]]
    valid_track_ids: set[int] | None
    annotated_video: Path | None
    elapsed: float
    detection_count: int = 0
    posture_counts: dict[str, int] = field(default_factory=dict)

    def outputs_of_type(self, data_type: str) -> dict[str, Any]:
        """``{model_id: value}`` for every completed model that produced ``data_type``."""
        return {m: r.outputs[data_type] for m, r in self.runs.items()
                if r.status == "completed" and data_type in r.outputs}


@dataclass
class Callbacks:
    on_progress: Callable[[float, str, dict], None] = lambda fraction, stage, detail: None
    on_model_status: Callable[[ModelRun], None] = lambda run: None
    is_cancelled: Callable[[], bool] = lambda: False


class ModelExecutor:
    def __init__(
        self,
        job_id: int,
        video_path: Path,
        pipeline: Pipeline,
        options: JobOptions,
        manager: ModelManager,
        store: JobResultStore,
        device: str,
        callbacks: Callbacks | None = None,
        fps_hint: float | None = None,
    ) -> None:
        self.job_id = job_id
        self.video_path = video_path
        self.pipeline = pipeline
        self.options = options
        self.manager = manager
        self.store = store
        self.device = device
        self.cb = callbacks or Callbacks()
        self.fps_hint = fps_hint
        self.runs = {s.model_id: ModelRun(s.model_id) for s in pipeline.steps}
        self.instances: dict[str, BaseVisionModel] = {}
        self.contexts: dict[str, JobContext] = {}
        self._started = 0.0
        self._last_progress = 0.0
        self._tmp: list[Path] = []
        self._weights = {"load": 0.03, "decode": 0.8, "post": 0.07, "render": 0.1}

    # ------------------------------------------------------------- helpers
    def _stage_weights(self, video: VideoInfo) -> dict[str, float]:
        """Progress share of each stage, proportional to its expected duration."""
        w = estimate_stages(self.pipeline, video.total_frames, video.frame_interval, video.width, video.height,
                            self.options.render_video, self.options.seconds_per_frame)
        total = sum(w.values()) or 1.0
        return {k: v / total for k, v in w.items()}

    def _stage_base(self, stage: str) -> float:
        order = ["load", "decode", "post", "render"]
        return sum(self._weights[s] for s in order[: order.index(stage)])

    def _progress(self, stage: str, fraction: float, label: str, detail: dict | None = None,
                  force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress < 0.25:
            return
        self._last_progress = now
        overall = min(0.995, self._stage_base(stage) + self._weights[stage] * max(0.0, min(1.0, fraction)))
        elapsed = now - self._started
        detail = dict(detail or {})
        detail["elapsed_seconds"] = round(elapsed, 1)
        if overall > 0.02:
            detail["eta_seconds"] = round(elapsed / overall * (1 - overall), 1)
        self.cb.on_progress(overall, label, detail)

    def _check_cancel(self) -> None:
        if self.cb.is_cancelled():
            raise ProcessingCancelled("Analysis was cancelled by the user.")

    def _set_status(self, model_id: str, status: str, error: str | None = None) -> None:
        run = self.runs[model_id]
        run.status = status
        if error:
            run.error = error
        self.cb.on_model_status(run)

    def _fail(self, model_id: str, error: str) -> None:
        """Mark a model failed and every model depending on it (transitively) skipped."""
        logger.error("Job %s: model %s failed: %s", self.job_id, model_id, error)
        self._set_status(model_id, "failed", error)
        changed = True
        while changed:
            changed = False
            for step in self.pipeline.steps:
                run = self.runs[step.model_id]
                if run.ok and any(not self.runs[d].ok for d in step.depends_on):
                    failed_dep = next(d for d in step.depends_on if not self.runs[d].ok)
                    self._set_status(step.model_id, "skipped",
                                     f"Skipped because '{failed_dep}' did not complete.")
                    changed = True

    def _active(self, kinds: tuple[str, ...]) -> list[PipelineStep]:
        return [s for s in self.pipeline.steps if s.spec.kind in kinds and self.runs[s.model_id].ok]

    # ----------------------------------------------------------------- run
    def run(self) -> ExecutionResult:
        self._started = time.monotonic()
        try:
            return self._run()
        except BaseException:
            for run in self.runs.values():
                if run.status in ("pending", "running"):
                    run.status = "cancelled"
            raise
        finally:
            for f in self._tmp:
                f.unlink(missing_ok=True)

    def _run(self) -> ExecutionResult:
        extractor = FrameExtractor(self.video_path, self.options.frame_interval,
                                   settings.max_inference_height, self.fps_hint)
        cap, fps, src_w, src_h, total = extractor.open()
        cap.release()
        if not src_w or not src_h:
            raise EmptyVideoError("The video has no readable frames.")
        width, height = processing_size(src_w, src_h, settings.max_inference_height)
        video = VideoInfo(fps=fps, width=width, height=height, source_width=src_w, source_height=src_h,
                          total_frames=total, duration=total / fps if fps else 0.0,
                          frame_interval=self.options.frame_interval)
        self._weights = self._stage_weights(video)

        # ---- 1. load frame/clip models (post models load later, to respect the memory limit)
        self._progress("load", 0.0, "Loading models", force=True)
        pinned = set(self.pipeline.model_ids)
        for step in self._active(("frame", "clip")):
            self._load(step, pinned)
        self._check_cancel()
        for step in self.pipeline.steps:
            self.contexts[step.model_id] = JobContext(
                job_id=self.job_id, model_id=step.model_id, config=step.config, video=video,
                device=self.device, is_cancelled=self.cb.is_cancelled,
                logger=logging.getLogger(f"vision.{step.model_id}"),
            )
        for step in self._active(("frame", "clip")):
            self._start(step)
        if not self._active(("frame", "clip", "post")):
            raise ProcessingError(self._all_failed_message())

        # ---- 2. single decode pass
        frame_steps = self._active(("frame", "clip"))
        writers = {s.model_id: self.store.writer(s.model_id) for s in frame_steps if s.spec.kind == "frame"}
        frame_stats: list[tuple[int, float, int]] = []
        detection_count = 0
        posture_counts: dict[str, int] = {}
        processed = 0
        decoded = 0
        try:
            for fr in extractor.frames():
                decoded += 1
                if decoded % 10 == 0:
                    self._check_cancel()
                if fr.sampled:
                    processed += 1
                    upstream = self._process_frame(FrameData(fr.index, fr.timestamp, fr.image), writers)
                    count = self._people_count(upstream)
                    if count is not None:
                        frame_stats.append((fr.index, fr.timestamp, count))
                    detection_count += len(upstream.get(dt.PERSON_DETECTIONS) or [])
                    for p in upstream.get(dt.POSTURE_LABELS) or []:
                        posture_counts[p["label"]] = posture_counts.get(p["label"], 0) + 1
                    self._progress("decode", fr.index / total if total else 0.0,
                                   "Running models on frames", {
                                       "frames_processed": processed, "frames_decoded": decoded,
                                       "total_frames": total or None,
                                       "processing_fps": round(decoded / (time.monotonic() - self._started), 2),
                                       "people_in_frame": count,
                                   })
        finally:
            for model_id, w in writers.items():
                w.close()
                w.write_meta(self._meta(model_id, video, w.frames_written))
        if decoded == 0:
            raise EmptyVideoError("No frames could be decoded from this video.")
        video.total_frames = decoded
        video.duration = decoded / fps

        # ---- 3. finish frame/clip models
        upstream_final: dict[str, Any] = {}
        for step in self._active(("frame", "clip")):
            self._check_cancel()
            self._finish(step, upstream_final)
        valid_tracks = self._valid_tracks(upstream_final)

        # ---- 4. post models
        post_steps = self._active(("post",))
        frame_model_ids = [m for m in writers if self.runs[m].ok]
        for i, step in enumerate(post_steps):
            self._check_cancel()
            if not self.runs[step.model_id].ok:
                continue
            self._progress("post", i / max(1, len(post_steps)), f"Running {step.spec.name}", force=True)
            self._load(step, pinned)
            if not self.runs[step.model_id].ok:
                continue
            self._start(step)
            n = len(post_steps)
            self.contexts[step.model_id].report = (
                lambda frac, msg=None, i=i, step=step: self._progress(
                    "post", (i + frac) / n, msg or f"Running {step.spec.name}"))
            self._post(step, frame_model_ids, upstream_final)

        # Drop job-level outputs belonging to tracks the tracker discarded as too short.
        if valid_tracks is not None:
            for run in self.runs.values():
                for key in (dt.ACTIVITY_SEGMENTS, dt.ACTIVITY_WINDOWS):
                    if key in run.outputs:
                        run.outputs[key] = [s for s in run.outputs[key] if s["track_id"] in valid_tracks]

        for model_id, run in self.runs.items():
            if run.status == "running":
                self._set_status(model_id, "completed")
            if run.outputs:
                self.store.writer(model_id).write_summary(run.outputs)

        if not any(r.status == "completed" for r in self.runs.values()):
            raise ProcessingError(self._all_failed_message())

        # ---- 5. render annotated video
        annotated = None
        if self.options.render_video and frame_model_ids:
            annotated = self._render(video, frame_model_ids, valid_tracks)

        elapsed = time.monotonic() - self._started
        return ExecutionResult(
            runs=self.runs, frames_decoded=decoded, frames_processed=processed, video=video,
            frame_stats=frame_stats, valid_track_ids=valid_tracks, annotated_video=annotated,
            elapsed=elapsed, detection_count=detection_count, posture_counts=posture_counts,
        )

    # -------------------------------------------------------------- stages
    def _load(self, step: PipelineStep, pinned: set[str]) -> None:
        run = self.runs[step.model_id]
        if not run.ok:
            return
        try:
            self.instances[step.model_id] = self.manager.get(step.model_id, self.device, pinned=pinned)
        except AppError as exc:
            self._fail(step.model_id, exc.message)
        except Exception as exc:
            self._fail(step.model_id, f"Could not load model: {exc}")

    def _start(self, step: PipelineStep) -> None:
        if not self.runs[step.model_id].ok:
            return
        try:
            inst = self.instances[step.model_id]
            ctx = self.contexts[step.model_id]
            inst.start_job(ctx)
            self.runs[step.model_id].weight_hashes = inst.weight_hashes(ctx.config)
            self._set_status(step.model_id, "running")
        except AppError as exc:
            self._fail(step.model_id, exc.message)
        except Exception as exc:
            logger.exception("start_job failed for %s", step.model_id)
            self._fail(step.model_id, f"Could not start: {exc}")

    def _process_frame(self, frame: FrameData, writers: dict) -> dict[str, Any]:
        upstream: dict[str, Any] = {}
        for step in self.pipeline.steps:
            if step.spec.kind not in ("frame", "clip"):
                continue
            run = self.runs[step.model_id]
            if not run.ok:
                continue
            t0 = time.perf_counter()
            try:
                out = self.instances[step.model_id].process_frame(frame, self.contexts[step.model_id], upstream)
            except ProcessingCancelled:
                raise
            except Exception as exc:
                logger.exception("Model %s failed on frame %d", step.model_id, frame.index)
                self._fail(step.model_id, f"Failed on frame {frame.index}: {exc}")
                continue
            finally:
                run.seconds += time.perf_counter() - t0
            out = out or {}
            if step.model_id in writers:
                writers[step.model_id].write(frame.index, frame.timestamp,
                                             {k: v for k, v in out.items() if k in dt.FRAME_TYPES})
            upstream.update(out)
        return upstream

    @staticmethod
    def _people_count(upstream: dict[str, Any]) -> int | None:
        if dt.PERSON_TRACKS in upstream:
            return len(upstream[dt.PERSON_TRACKS])
        if dt.PERSON_DETECTIONS in upstream:
            return len(upstream[dt.PERSON_DETECTIONS])
        return None

    def _finish(self, step: PipelineStep, upstream_final: dict[str, Any]) -> None:
        run = self.runs[step.model_id]
        if not run.ok:  # a dependency may have failed while finishing
            return
        ctx = self.contexts[step.model_id]
        ctx.upstream_final = upstream_final
        t0 = time.perf_counter()
        try:
            outputs = self.instances[step.model_id].finish(ctx) or {}
        except ProcessingCancelled:
            raise
        except Exception as exc:
            logger.exception("finish() failed for %s", step.model_id)
            self._fail(step.model_id, f"Could not finalise results: {exc}")
            return
        finally:
            run.seconds += time.perf_counter() - t0
        run.outputs.update(outputs)
        upstream_final.update(outputs)
        self._set_status(step.model_id, "completed")

    def _post(self, step: PipelineStep, frame_model_ids: list[str], upstream_final: dict[str, Any]) -> None:
        run = self.runs[step.model_id]
        ctx = self.contexts[step.model_id]
        ctx.upstream_final = upstream_final
        t0 = time.perf_counter()
        try:
            reader = self.store.reader(frame_model_ids)
            outputs = self.instances[step.model_id].process_results(reader, ctx) or {}
        except ProcessingCancelled:
            raise
        except Exception as exc:
            logger.exception("process_results() failed for %s", step.model_id)
            self._fail(step.model_id, f"Failed: {exc}")
            return
        finally:
            run.seconds += time.perf_counter() - t0
        run.outputs.update(outputs)
        upstream_final.update(outputs)
        self._set_status(step.model_id, "completed")

    @staticmethod
    def _valid_tracks(upstream_final: dict[str, Any]) -> set[int] | None:
        summaries = upstream_final.get(dt.TRACK_SUMMARIES)
        if summaries is None:
            return None
        return {int(s["track_id"]) for s in summaries}

    def _meta(self, model_id: str, video: VideoInfo, frames_written: int) -> dict:
        spec = self.pipeline.step(model_id).spec
        return {
            "model_id": model_id, "version": spec.version, "kind": spec.kind, "produces": spec.produces,
            "coord_width": video.width, "coord_height": video.height, "fps": video.fps,
            "frame_interval": video.frame_interval, "chunk_seconds": self.store.chunk_seconds,
            "frames_written": frames_written,
        }

    def _all_failed_message(self) -> str:
        errors = [f"{m}: {r.error}" for m, r in self.runs.items() if r.error]
        return "No model could run. " + " | ".join(errors) if errors else "No model could run."

    # -------------------------------------------------------------- render
    def _render(self, video: VideoInfo, frame_model_ids: list[str], valid_tracks: set[int] | None) -> Path | None:
        self._progress("render", 0.0, "Rendering annotated video", force=True)
        segments = self._segments_by_model()
        annotator = FrameAnnotator(self.options.overlay, video.width, video.height,
                                   ActivityLookup(segments) if segments else None)
        settings.temp_dir.mkdir(parents=True, exist_ok=True)
        tmp = settings.temp_dir / f"render-{self.job_id}-{uuid.uuid4().hex}.mp4"
        self._tmp.append(tmp)
        writer = open_writer(tmp, video.width, video.height, video.fps)
        records = self.store.iter_merged(frame_model_ids)
        nxt = next(records, None)
        persons: list[dict] = []
        try:
            for fr in FrameExtractor(self.video_path, 1, settings.max_inference_height, self.fps_hint).frames():
                if fr.index % 10 == 0:
                    self._check_cancel()
                while nxt is not None and nxt[0] <= fr.index:
                    persons = merge_persons(nxt[2], valid_tracks)  # hold until the next processed frame
                    nxt = next(records, None)
                annotator.draw(fr.image, persons, fr.timestamp)
                writer.write(fr.image)
                self._progress("render", fr.index / max(1, video.total_frames), "Rendering annotated video",
                               {"frames_rendered": fr.index + 1, "total_frames": video.total_frames})
            writer.close()
        except BaseException:
            writer.abort()
            raise
        out = settings.temp_dir / f"annotated-{self.job_id}-{uuid.uuid4().hex}.mp4"
        self._tmp.append(out)
        if not (settings.keep_audio and mux_audio(tmp, self.video_path, out)):
            shutil.copyfile(tmp, out)
        final = settings.temp_dir / f"annotated-{self.job_id}.mp4"
        out.replace(final)
        return final

    def _segments_by_model(self) -> dict[str, list[dict]]:
        return {m: r.outputs[dt.ACTIVITY_SEGMENTS] for m, r in self.runs.items()
                if r.status == "completed" and dt.ACTIVITY_SEGMENTS in r.outputs}
