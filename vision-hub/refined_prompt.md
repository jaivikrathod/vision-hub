# Project: Vision Hub — Modular Computer Vision Video Intelligence Platform

## 0. Starting Point and Constraints

- **Existing code:** `human-tracking-system/` is a working YOLO11 + ByteTrack person-tracking web app (FastAPI, SQLAlchemy, Alembic, SQLite, background worker, SSE progress, React + Vite + Tailwind).
- **Backup:** a frozen copy exists at `human-tracking-system-backup/`. Never modify the backup.
- **Rename:** rename `human-tracking-system/` to `vision-hub/` and evolve it into the new platform.
- **Reuse freely:** video I/O, upload validation and security checks, H.264/FFmpeg output, device selection, weight resolution, worker and queue patterns, SSE progress hook, layout, UI components, upload area, video player, tests.
- **Replace:** the hardcoded single-pipeline processing (`video_processing_service.py`) and the tracking-specific, per-video processing state.
- **Hardware:** **CPU only, no GPU.** Every default must run acceptably on a laptop CPU. GPU support stays automatic if one is present later.
- **Data:** no custom training datasets. Use pretrained models, zero-shot models, and transparent rule-based logic over model outputs.
- **After the rename:** recreate the Python virtual environment (a venv stores absolute paths and breaks when its folder moves). Start with a fresh database; the backup keeps the old data.
- **Existing pages:** keep Settings and About. Fold History into the analysis job list.

---

## 1. Goal

A web application where the user:

1. Uploads a video.
2. Chooses one or more models from a **Model Library** for their current purpose.
3. Configures those models.
4. Runs analysis in the background with live progress.
5. Sees exactly what each selected model found: interactive overlays, analytics and per-person timelines.

**Most important principle:** every AI model is an independent, replaceable plugin behind a common interface. Adding a new model means writing one class and registering it. No changes to API routes, the worker, the database schema or the frontend forms.

---

## 2. Scope

### Build now

| Model ID | Name | Category |
|---|---|---|
| `human_pose` | Human Detection & Pose Estimation | pose |
| `human_tracking` | Human Tracking | tracking |
| `activity_pose_temporal` | Activity Recognition (Pose-based, fast) | activity |
| `activity_xclip` | Activity Recognition (X-CLIP zero-shot, heavier) | activity |

Shipping two activity implementations in the same category is deliberate. It proves that models are replaceable behind one interface.

### Do not build now (but the architecture must support them)

Vehicle detection and classification, traffic violations, general object detection, tracking and segmentation, OCR, face recognition, depth estimation, human-object interaction, hand gestures, industrial defect detection, scene understanding.

---

## 3. Technology Stack

**Backend:** Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, pydantic-settings, OpenCV (headless), NumPy, imageio-ffmpeg (bundled FFmpeg).

**AI:** PyTorch (CPU wheels), Ultralytics **pinned to `8.4.x`** (YOLO11-pose, ByteTrack), Hugging Face `transformers` (X-CLIP). VideoMAE is optional and must not be the default.

**Frontend:** React 18, Vite, JavaScript, Tailwind CSS, Axios, React Router, Recharts, lucide-react.

**Before adding any model weights,** verify and record:

- license
- class list or label capability
- dependency versions
- CPU inference cost

Note: Ultralytics YOLO11 is **AGPL-3.0**. That is fine for learning and personal use. Record it in the Model Library.

---

## 4. Core Concepts

- **Model:** a plugin that declares what it needs and what it produces.
- **Data types:** named, typed outputs that models exchange:
  - `person_detections`: per frame, boxes and confidence
  - `person_keypoints`: per frame, per person, 17 COCO keypoints
  - `posture_labels`: per frame, per person
  - `person_tracks`: track IDs per frame, plus trajectories
  - `activity_segments`: per track, a time range, a label, a confidence and the method that produced it
- **Analysis job:** one video plus the selected models and their configuration.
- **Pipeline:** the order in which models run, built automatically from the declared inputs and outputs. Later, users can save named pipelines; there is no UI for this now, but the data model must allow it.

---

## 5. Model Interface

Every model provides a **ModelSpec** (metadata) and an implementation.

```python
class ModelSpec(BaseModel):
    model_id: str                 # "human_pose"
    name: str
    category: str                 # "pose" | "tracking" | "activity" | future...
    version: str                  # semantic version of the plugin + weights
    description: str
    license: str
    weights: list[WeightInfo]     # file name, source URL, sha256, size
    requires: list[str]           # data types consumed, e.g. ["person_tracks", "person_keypoints"]
    produces: list[str]           # data types produced
    kind: Literal["frame", "clip", "post"]   # see below
    config_schema: type[BaseModel]           # Pydantic model -> JSON Schema for the UI
    cost_hint: str                # e.g. "~15 FPS on 4-core CPU at 640px"


class BaseVisionModel(ABC):
    spec: ModelSpec

    def load(self, device: str) -> None: ...
    def unload(self) -> None: ...

    # kind == "frame": called for every sampled frame in a single decode pass
    def process_frame(self, frame: FrameData, context: FrameContext, config) -> dict: ...

    # kind == "clip": called with temporal windows (e.g. per track)
    def process_clip(self, clip: ClipData, context: ClipContext, config) -> dict: ...

    # kind == "post": runs once over all upstream results (e.g. pose-based activity)
    def process_results(self, results: ResultStore, config) -> dict: ...
```

Rules:

- The model executor is the only code that calls models. API routes never call models.
- Models never read the video file themselves. They receive frames, clips or results from the executor.
- Models never write to the database. They return structured outputs, and the executor stores them.
- Each model's `config_schema` is exposed as JSON Schema, and the frontend builds the configuration form from it automatically.
- **Passing data between models in the same frame:** outputs of earlier models are available to later ones as `context.upstream["<data type>"]`, for example `context.upstream["person_detections"]`.
- **Time is measured in seconds, not frames.** Windows, speeds and clip spans use timestamps, so results don't change with the frame interval or the video's frame rate.

---

## 6. Execution Engine

Backend modules: `model_registry.py`, `model_manager.py`, `model_executor.py`, `pipeline_planner.py`, `frame_extractor.py`, `video_processor.py`, `result_store.py`, `annotator.py`.

**Registry**
- Discovers and registers plugins.
- The code is the source of truth. At startup it syncs the `vision_models` table, so model status, version and weight availability are visible in the UI.

**Pipeline planner**
- Given the selected model IDs, it resolves the `requires`/`produces` dependencies into an ordered graph and rejects circular dependencies.
- If a selected model needs data no selected model provides, it auto-adds the provider and marks it `auto_added`. Example: selecting only Activity auto-adds Tracking and Pose. When several installed models can provide the same data, `ModelSpec.priority` decides which one is added.
- The UI shows auto-added models before the job starts.

**Model manager**
- Lazy-loads models and caches loaded instances.
- Never loads the same weights twice.
- Enforces a maximum number of loaded models (default 2 on CPU) and unloads the least recently used one when over the limit. The limit counts only models with neural-network weights; rule-based models (tracker, pose-based activity) don't count.
- Reports missing or corrupt weights as clear errors.

**Executor**
- **Single decode pass:** reads the video once and feeds each sampled frame to all `frame` models in dependency order.
- Then runs `clip` and `post` models.
- Supports a configurable frame interval and batching.
- Never loads the full video into RAM.
- Handles corrupt or unreadable frames gracefully.
- Supports cancellation.
- Reports progress per stage and overall, weighted by expected cost.
- Records execution time and status per model.
- Produces the annotated MP4 export from the stored results after inference.

**Detection is not duplicated:** `human_tracking` consumes `person_detections` from `human_pose` (YOLO11n-pose already outputs person boxes) instead of running a second detector.

**Tracker adapter:** feeding outside detections into ByteTrack means calling Ultralytics' `BYTETracker` directly, which is an internal API. Wrap it in a small adapter class, pin the Ultralytics minor version, and cover it with a test. Each track ID is matched back to its detection (and keypoints) by detection index.

**Clip models stay in the single pass:** ByteTrack is online, so track IDs exist frame by frame. Clip models such as X-CLIP keep a small, capped buffer of person crops per active track and run when a window is full. Memory stays bounded. Results for tracks later dropped as too short are discarded.

**Skipped frames:** with frame interval > 1, overlays keep showing the last processed result until the next processed frame.

**CPU threads:** the worker limits PyTorch's thread count (`torch.set_num_threads`) so the API and the machine stay responsive.

---

## 7. Model Specifications

### 7.1 `human_pose`: Human Detection & Pose Estimation (frame model)

- **Weights:** YOLO11n-pose by default; YOLO11s-pose as a configurable option.
- **Outputs per person per frame:** bounding box, detection confidence, 17 COCO keypoints with confidence, and a per-frame posture label.
- **Posture classification:** rule-based keypoint geometry (torso angle, hip-knee-ankle angles, box aspect ratio):
  - Labels: standing, sitting, lying down, bending, `unknown`.
  - Thresholds are configurable.
  - Return `unknown` when the required keypoints are missing or have low confidence. Never force a label.
  - Document that camera angle affects accuracy.
- **Config:** confidence threshold, image size (default 640), keypoint confidence threshold, posture thresholds.

### 7.2 `human_tracking`: Human Tracking (frame model)

- **Requires** `person_detections`. Runs ByteTrack (Ultralytics implementation) on top of them.
- **Outputs:** tracking ID per detection per frame, timestamps, trajectories (box-center path), first and last seen time per track.
- **Config:** track buffer, match threshold, minimum track length (drop tracks shorter than N frames).
- **Document:** large frame intervals reduce tracking quality.

### 7.3 `activity_pose_temporal`: Pose-based Activity Recognition (post model, default)

- **Requires** `person_tracks` and `person_keypoints`.
- Analyses fixed-length sliding windows per track. Window length and stride are configurable; defaults are 1.5 s and 0.5 s.
- **Signals used:**
  - hip-center speed normalised by body height
  - vertical oscillation
  - airborne phase (both ankles rise above the baseline)
  - posture distribution within the window
  - torso angle change rate
- **Labels:** walking, running, jumping, standing, sitting, lying down, bending, `falling (heuristic)`, `uncertain`.
- **Output:** for each window, a score for every label, a top label and a confidence. Windows are then smoothed (hysteresis or majority filter) and merged into segments.
- Below the confidence threshold the result is `uncertain`. A single frame is never enough evidence for an activity.
- **Fast on CPU:** no extra neural network.

### 7.4 `activity_xclip`: Zero-shot Activity Recognition (clip model, optional)

- **Model:** `microsoft/xclip-base-patch32` (Hugging Face). Verify its license before use. The download is several hundred MB: show this on the model card and download only on first use.
- **Requires** `person_tracks`. Builds clips from each track's cropped person region (with a margin, padded to a square so people don't look stretched), sampling 8 frames per clip.
- **Labels:** user-editable. Each label has a **display name** (shown in the UI) and a separate **text prompt** sent to the model (e.g. display "walking", prompt "a person walking"), so no training is needed. "Falling" is excluded; it stays a pose-based heuristic only.
- **Outputs:** per-clip label probabilities, smoothed and merged into activity segments.
- **CPU safeguards:**
  - configurable clip stride
  - maximum number of clips per track
  - maximum number of tracks
  - the UI shows an estimated runtime before the job starts
- Results are labelled with their method, so the user can compare them with `activity_pose_temporal` when both are selected.

**General honesty rule:** never hardcode, fake or mock predictions. Every label shown in the UI must come from stored inference output, tagged with the model ID and version that produced it.

---

## 8. Storage Design

**Files** (under `storage/`):
- `uploads/`: original videos
- `playback/`: an H.264 copy, made during scanning only when the original isn't playable in browsers (HEVC, AVI, etc.)
- `thumbnails/`
- `results/{job_id}/{model_id}/chunk_{n}.jsonl.gz`: detailed per-frame results, stored in **10-second chunks** so the overlay endpoint can load any time range without decompressing the whole file
- `exports/{job_id}/annotated.mp4`

**SQLite tables** (via Alembic migrations):

- **`videos`**: id, filename, file_path, thumbnail_path, size_bytes, duration, fps, width, height, total_frames, codec, status (`uploaded | scanning | ready | failed`), error_message, created_at
- **`vision_models`**: id, model_id, name, category, version, description, license, weights_info, config_schema, default_config, requires, produces, status (`available | weights_missing | error | disabled`), created_at, updated_at
- **`analysis_jobs`**: id, video_id, status (`queued | processing | completed | failed | cancelled`), progress, current_stage, queued_at, started_at, completed_at, heartbeat_at, error_message
- **`analysis_job_models`**: id, job_id, model_id, model_version, weights_sha256, configuration, auto_added, execution_status, execution_time, error_message, result_path
- **`tracked_persons`**: id, job_id, track_id, first_seen, last_seen, frame_count, avg_confidence, trajectory_summary
- **`activity_segments`**: id, job_id, model_id, track_id, start_time, end_time, label, confidence, method
- **`frame_stats`**: id, job_id, timestamp, people_count. One row per processed frame, for the people-over-time chart.
- **`model_benchmarks`**: model_id, model_version, device, seconds_per_frame, measured_at. Used for runtime estimates.

The per-frame `detection_results` table from the original prompt is replaced by the chunked results files.

Never store frames as database BLOBs.

**SQLite with two processes:** the API and the worker share the file. Use WAL mode, a `busy_timeout`, and an atomic job claim (`UPDATE … RETURNING`).

---

## 9. API

**Videos**
- `POST /api/videos/upload`: validates extension, content, size and duration
- `GET /api/videos`: paginated
- `GET /api/videos/{id}`
- `GET /api/videos/{id}/stream`: supports HTTP range requests
- `GET /api/videos/{id}/thumbnail`
- `DELETE /api/videos/{id}`: also deletes its jobs and files

**Models**
- `GET /api/models`
- `GET /api/models/{model_id}`
- `GET /api/models/{model_id}/configuration`: JSON Schema plus defaults

**Analysis**
- `POST /api/analysis/plan`: takes the video and selected models; returns the resolved pipeline, auto-added models, validation errors and an estimated runtime
- `POST /api/analysis/start`
- `GET /api/analysis`: list of jobs
- `GET /api/analysis/{job_id}`
- `GET /api/analysis/{job_id}/progress`: SSE stream
- `POST /api/analysis/{job_id}/cancel`
- `GET /api/analysis/{job_id}/results`: summary and analytics
- `GET /api/analysis/{job_id}/frames?start=&end=`: per-frame overlay data for a time range, for the canvas
- `GET /api/analysis/{job_id}/persons`
- `GET /api/analysis/{job_id}/activities`
- `GET /api/analysis/{job_id}/annotated-video`

---

## 10. Background Worker

- A **separate worker process**: `python -m app.workers.analysis_worker`.
- **Queue:** a job queue stored in SQLite.
  - Claiming a job is atomic.
  - The worker updates a heartbeat while it runs.
  - At startup, stale jobs (heartbeat expired) are marked failed.
- **Concurrency:** one job at a time by default; configurable.
- **Progress:** the worker writes progress to the database, throttled. The API's SSE endpoint streams it.
- **Scaling later:** hide the queue behind a small `JobQueue` interface so it can be swapped for Redis or Celery without touching the executor.
- **One-command start:** provide a single dev command or script that starts the API, the worker and the frontend.

---

## 11. Frontend

### Pages
1. Dashboard
2. Upload Video
3. Video Library
4. Model Library
5. Model Details
6. Configure Analysis
7. Analysis Processing
8. Analytics Results

### Configure Analysis
- Pick a video and select model cards.
- Configuration forms are generated automatically from each model's JSON Schema.
- Show the resolved pipeline (including auto-added models) and the estimated CPU runtime before starting.

### Results
- **Video player:** the original video with a **canvas overlay** drawn live from the per-frame results.
- **Independent toggles:** bounding boxes, track IDs, skeleton, posture labels, activity labels, confidence scores.
- **Annotated MP4:** a separate tab and a download.
- **Player controls:** play/pause, timeline, current timestamp, and clicking a timeline segment seeks the video.

### Analytics
All analytics come from stored results:
- unique people tracked
- total detections
- activity distribution
- posture distribution
- average activity confidence
- per-person activity timeline (Gantt-style; one row per person)
- people-over-time chart

### Status badges
- **Videos:** uploaded, scanning, ready, failed
- **Jobs:** queued, processing, completed, failed, cancelled

---

## 12. Folder Structure

```text
vision-hub/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/            # videos.py, models.py, analysis.py
│   │   ├── core/           # database.py, security.py, exceptions.py
│   │   ├── db/             # database_models.py
│   │   ├── schemas/        # Pydantic API schemas
│   │   ├── services/       # video_service.py, analysis_service.py, analytics_service.py
│   │   ├── vision/
│   │   │   ├── base_model.py
│   │   │   ├── data_types.py
│   │   │   ├── model_registry.py
│   │   │   ├── model_manager.py
│   │   │   ├── pipeline_planner.py
│   │   │   ├── model_executor.py
│   │   │   ├── frame_extractor.py
│   │   │   ├── video_processor.py
│   │   │   ├── result_store.py
│   │   │   ├── annotator.py
│   │   │   └── plugins/
│   │   │       ├── human_pose/
│   │   │       ├── human_tracking/
│   │   │       ├── activity_pose_temporal/
│   │   │       └── activity_xclip/
│   │   └── workers/
│   │       ├── job_queue.py
│   │       └── analysis_worker.py
│   ├── migrations/
│   ├── storage/            # uploads/, thumbnails/, results/, exports/
│   ├── model_weights/
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   └── src/                # pages/, components/, services/, hooks/, context/
├── scripts/                # dev.sh, download_weights.py
└── README.md
```

---

## 13. Performance and Reliability (CPU-first)

- **CPU defaults:**
  - YOLO11n-pose at 640 px
  - frame interval 1–2 (configurable)
  - `activity_pose_temporal` as the default activity model
  - `activity_xclip` opt-in only
- Show an estimated runtime before the job starts, and live processing FPS and ETA during it.
  - **How it's calculated:** each model's measured seconds per processed frame on this machine (updated after every completed job and saved in `model_benchmarks`), multiplied by the number of frames to process. Before the first run, each model's built-in default is used and the UI says the estimate is a first guess.
- **Limits** (configurable):
  - maximum video length 10 minutes by default
  - videos above 1080p are downscaled for inference
  - an option to delete results older than N days
- Limit the PyTorch thread count sensibly so the API stays responsive.
- **Error handling:** handle corrupt videos, missing weights, out-of-memory errors and failures of an individual model.
  - A failed model marks its own row as failed and fails the models that depend on it.
  - Independent models still finish.
- **Reproducibility:** store the model version, weights SHA-256, full configuration and frame-sampling settings for every job model. Use deterministic settings where possible.
  - Ultralytics doesn't publish official hashes, so compute and record the SHA-256 on first download.

**Tests:** the "no fake predictions" rule applies to the product, not the tests. Tests use fake plugins and a small generated video, and never download weights. Tests that need real weights are marked and skipped when the weights are missing.

---

## 14. Development Phases (test each before moving on)

**Phase A: Core architecture**
- Rename the project; apply the new schema and migrations.
- Build the registry, manager, planner, executor, result store, worker and queue.
- Move YOLO + ByteTrack behind `human_pose` and `human_tracking`.
- **Acceptance:** a tracking job started over the API produces track counts and an annotated video comparable to the old app. Unit tests cover the planner, the registry and the queue.

**Phase B: Pose and posture**
- Keypoints, skeleton and posture rules.
- **Acceptance:** keypoints and postures are stored and drawn. Posture rules have unit tests built on synthetic keypoints.

**Phase C: Activity**
- `activity_pose_temporal`, then `activity_xclip`.
- **Acceptance:** activity segments per track, with confidences and an `uncertain` label. Tests cover the windowing and smoothing.

**Phase D: Frontend**
- All pages, schema-driven configuration forms, canvas overlays with toggles, analytics and timelines.
- **Acceptance:** the full flow works in the browser on a sample video.

**Phase E: Hardening and documentation**
- Error cases, cancellation, restart recovery, README.

---

## 15. Deliverables

- Working code (not snippets) and passing tests.
- README covering:
  - installation (CPU PyTorch wheels)
  - downloading weights (`scripts/download_weights.py`, with SHA-256 checks)
  - `.env` configuration
  - database migrations
  - one-command dev start, plus separate API, worker and frontend commands
  - testing with a sample video (with suggested free sample sources)
- Documentation per model: classes and labels, method, license, known limitations and CPU cost.
- A short "How to add a new model" guide that shows the minimal plugin.
