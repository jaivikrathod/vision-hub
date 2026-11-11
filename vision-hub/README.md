# Vision Hub: Modular Computer Vision Video Intelligence Platform

Upload a video, choose which computer vision models to run, and see exactly what each one finds, with live overlays, per-person activity timelines and analytics.

Every AI model is an **independent plugin behind one interface**. Adding a model means adding one Python package; the API, worker, database and frontend forms don't change.

Everything runs locally. Videos never leave your computer, and the defaults are tuned for **CPU-only** laptops. An NVIDIA GPU is used automatically if present.

---

## Contents

1. [What it does](#what-it-does)
2. [Models](#models)
3. [Architecture](#architecture)
4. [Installation](#installation)
5. [Model weights](#model-weights)
6. [Configuration](#configuration)
7. [Database](#database)
8. [Running the app](#running-the-app)
9. [Testing with sample videos](#testing-with-sample-videos)
10. [Adding a new model](#adding-a-new-model)
11. [API](#api)
12. [Tests](#tests)
13. [Troubleshooting](#troubleshooting)
14. [Scaling later](#scaling-later)

---

## What it does

- **Upload** (MP4, AVI, MOV, MKV)
  - The extension and the real file content are both validated.
  - Duplicates are detected by SHA-256.
  - Size and duration limits apply.
- **Scan**
  - Reads duration, FPS, resolution, frame count, codec and audio, and creates a thumbnail.
  - Formats browsers can't play (DivX/AVI, HEVC…) get an **H.264 playback copy** automatically.
- **Model library**: cards with each model's ID, category, version, inputs and outputs, status, license, measured speed on *your* machine, and the weight files with their SHA-256.
- **Configure analysis**
  - Pick a video and any combination of models.
  - Each model's settings form is **generated from its schema**.
  - A live **pipeline preview** shows auto-added dependencies, the run order, a runtime estimate and warnings.
- **Background processing**
  - A separate worker process reads the video **once**; every processed frame flows through all per-frame models.
  - Progress is live (Server-Sent Events) with FPS, ETA and per-model status. Jobs can be cancelled.
- **Results**
  - The original video plays with a **canvas overlay drawn live** from stored results, with independent toggles for boxes, IDs, skeleton, posture, activity and confidence.
  - Also available: an annotated MP4 download, a person-wise activity timeline (click a segment to seek), people-over-time, posture and activity distributions, a per-person table, a JSON export, and a reproducibility panel (model versions, weight hashes, exact settings).

Nothing is mocked. Every number and label in the UI comes from stored inference output, tagged with the model and version that produced it.

---

## Models

| Model ID | Name | Kind | Method | License | Weights |
|---|---|---|---|---|---|
| `human_pose` | Human Detection & Pose Estimation | frame | YOLO11-pose (17 COCO keypoints) + rule-based posture | AGPL-3.0 (Ultralytics) | 6 MB (n) / 20 MB (s) |
| `human_tracking` | Human Tracking | frame | ByteTrack over the pose model's person boxes | MIT algorithm / AGPL-3.0 implementation | none |
| `activity_pose_temporal` | Activity Recognition (Pose-based) | post | Sliding windows over keypoint sequences; transparent rules | MIT (this project) | none |
| `activity_xclip` | Activity Recognition (X-CLIP zero-shot) | clip | `microsoft/xclip-base-patch32`, text prompts per activity | MIT | ~790 MB |

**Measured on a 12-core laptop CPU:**
- YOLO11n-pose: about 13 frames/s at 640 px, 7 at 960 px (the default), and 4 at 1280 px.
- X-CLIP: about 0.8 s per 8-frame clip per person.
- A 12 s 1080p clip with all four models takes about 40 s at frame interval 2.

**Detection resolution matters more than model size for small people.** On OpenCV's 768×576 pedestrian clip, YOLO11n-pose found:

| Detection size | People found per frame |
|---|---|
| 640 px | 0.4 |
| 960 px (default) | 3.2 |
| 1280 px | 5.0 |

The planner suggests 1280 for low-resolution videos.

### Postures (`human_pose`)

**Labels:** standing, sitting, lying down, bending, or `unknown`.

**How they're computed:** from torso angle, knee angle and "thigh drop" (how far the knees sit below the hips, relative to torso length).

**When you get `unknown`:** whenever the hips, shoulders or legs aren't visible. The model doesn't guess.

### Activities

**Activity classes:** walking, running, jumping, standing, sitting, lying down, bending, falling, plus `uncertain` when the evidence is weak.

**Why there is no single pretrained model for this:** no pretrained model outputs exactly this list. For example, Kinetics-400 (used by VideoMAE) has no plain "standing", "sitting" or "walking" classes. Two methods are provided instead, and you can run both side by side.

- **Pose-based (default, fast)**
  - Each tracked person is analysed in 1.5 s windows using:
    - hip velocity and change in apparent size, both normalised by body height
    - left/right ankle alternation (gait) and step rate, so walking is still detected when the camera follows the person
    - foot rise (jumps)
    - fast hip drop ending lying down (falls; marked as a heuristic)
    - the posture mix over the window
  - Window results are smoothed and merged into segments.
  - A single frame never decides an activity.
- **X-CLIP zero-shot (optional, heavier)**
  - Clips of each tracked person (8 square crops over 2 s) are matched against editable text prompts ("a video of a person walking").
  - No training is needed.
  - "Falling" is not offered here; it is only a pose-based heuristic.

**Known limitations.** These are also listed on each model's page in the app:
- Posture rules depend on camera angle.
- Motion straight towards or away from the camera is estimated from size change.
- Zero-shot accuracy depends on prompt wording.

---

## Architecture

```text
 Browser (React + Vite)                API process (FastAPI)              Worker process
 ─────────────────────                 ─────────────────────              ──────────────
 Upload / Library / Configure  ──REST─▶ routes (thin)                      analysis_worker.py
 Results: canvas overlays      ◀─SSE── services (video, analysis,         ├─ claims jobs (SQLite queue,
                                         analytics, models)                │  atomic UPDATE … RETURNING)
                                         │                                 ├─ heartbeat + worker_status.json
                                         ▼                                 └─ ModelExecutor
                                SQLite (WAL, shared) ◀──────────────────────── │
                                storage/  uploads · playback · thumbnails      ├─ PipelinePlanner (requires/produces)
                                          results/{job}/{model}/chunk_*.gz     ├─ ModelManager (lazy load, LRU)
                                          exports/{job}/annotated.mp4          ├─ FrameExtractor (single pass)
                                                                               ├─ plugins (BaseVisionModel)
                                                                               └─ Annotator (MP4 export)
```

### Key ideas

- **Models declare their needs and outputs**
  - Each model lists the data types it needs (`requires`) and outputs (`produces`), for example `person_detections`, `person_keypoints`, `person_tracks`, `activity_segments`.
  - The planner orders models and **auto-adds** providers. Selecting only Activity adds Pose and Tracking.
  - When two installed models can provide the same data, `ModelSpec.priority` decides which one is added.
- **Three kinds of model**
  - `frame`: called for every processed frame.
  - `clip`: also gets every frame, buffers per-person clips, and outputs per window.
  - `post`: runs once over the stored results.
- **One decode pass**: tracking uses the pose model's boxes, so people are detected once. ByteTrack is online, so X-CLIP buffers crops during the same pass, with bounded memory.
- **Chunked results**: per-frame outputs go to gzipped JSON Lines in 10-second chunks, so the overlay API loads any time range cheaply. SQLite stores summaries: persons, activity segments, per-frame people counts.
- **Failure isolation**: a failing model marks itself `failed` and its dependents `skipped`; independent models still finish.
- **Reproducibility**: every job model records its version, weight SHA-256, full configuration and the frame interval.
- **CPU-friendly**
  - PyTorch threads are capped at cores − 2.
  - At most 2 neural models stay loaded (least recently used is unloaded first).
  - Frames above 1080p are downscaled for inference.
  - Runtime estimates are calibrated from real runs on your machine.

### Folder structure

```text
vision-hub/
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI app (API process)
│   │   ├── config.py                  settings (.env)
│   │   ├── api/                       videos.py · models.py · analysis.py · dashboard.py
│   │   ├── core/                      database.py · security.py · exceptions.py
│   │   ├── db/database_models.py      SQLAlchemy tables
│   │   ├── schemas/                   Pydantic API schemas
│   │   ├── services/                  video · analysis · analytics · model services
│   │   ├── vision/
│   │   │   ├── base_model.py          BaseVisionModel, ModelSpec (the plugin interface)
│   │   │   ├── data_types.py          named data types exchanged between models
│   │   │   ├── model_registry.py      plugin discovery + DB sync
│   │   │   ├── model_manager.py       lazy loading, reuse, LRU limit
│   │   │   ├── pipeline_planner.py    dependency resolution and ordering
│   │   │   ├── model_executor.py      single-pass execution engine
│   │   │   ├── frame_extractor.py     streaming frames, sampling, downscaling
│   │   │   ├── video_processor.py     scanning, thumbnails, playback copies
│   │   │   ├── video_io.py            probing, H.264 writer, audio mux
│   │   │   ├── result_store.py        chunked result files
│   │   │   ├── annotator.py           MP4 overlay rendering
│   │   │   ├── activity_utils.py      windows, smoothing, segments
│   │   │   ├── weights.py             device selection, downloads, SHA-256
│   │   │   └── plugins/               human_pose · human_tracking · activity_pose_temporal · activity_xclip
│   │   └── workers/                   job_queue.py · analysis_worker.py
│   ├── migrations/                    Alembic
│   ├── storage/                       uploads · playback · thumbnails · results · exports · tmp
│   ├── model_weights/
│   └── tests/
├── frontend/src/                      pages · components · hooks · services · context · lib
└── scripts/                           dev.sh · download_weights.py
```

---

## Installation

Tested on Ubuntu 24.04 with Python 3.12 and Node 24.

### 1. System packages

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip curl
# Node.js 22 LTS or newer (skip if `node --version` is >= 20.19)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
```

You don't need a system FFmpeg; the `imageio-ffmpeg` package bundles one.

### 2. Backend

```bash
cd vision-hub/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# PyTorch first - CPU wheels (small). For NVIDIA GPUs see https://pytorch.org
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
cp .env.example .env            # optional: adjust settings
```

### 3. Frontend

```bash
cd vision-hub/frontend
npm install
```

---

## Model weights

Weights are downloaded **once** into `backend/model_weights/`, either automatically on first use or ahead of time. Pre-downloading is recommended for X-CLIP because of its size:

```bash
cd vision-hub
backend/.venv/bin/python scripts/download_weights.py              # everything (~820 MB)
backend/.venv/bin/python scripts/download_weights.py --skip-large # YOLO pose only (~26 MB)
backend/.venv/bin/python scripts/download_weights.py human_pose   # one model
```

| File | Source | Size | License |
|---|---|---|---|
| `yolo11n-pose.pt` | github.com/ultralytics/assets releases | 6 MB | AGPL-3.0 |
| `yolo11s-pose.pt` | github.com/ultralytics/assets releases | 20 MB | AGPL-3.0 |
| `xclip-base-patch32/` | huggingface.co/microsoft/xclip-base-patch32 (safetensors only) | 790 MB | MIT |

- **Hashes:** the SHA-256 of each file is computed after download and stored as `<file>.sha256`. Jobs record it, and the Model Details page shows it.
- **Offline use:** set `ALLOW_MODEL_DOWNLOAD=false` once the weights are present.
- **AGPL-3.0:** this applies to Ultralytics YOLO11. It's fine for learning and personal use; shipping it inside closed-source software needs an Ultralytics commercial license.

---

## Configuration

All settings live in `backend/.env`; defaults are in `backend/.env.example`. The most useful ones:

| Setting | Default | Meaning |
|---|---|---|
| `DEVICE` | `auto` | `auto` uses CUDA if available, else CPU. Also `cpu`, `cuda:0`, `mps` |
| `TORCH_THREADS` | cores − 2 | CPU threads the worker uses for inference |
| `MAX_LOADED_MODELS` | `2` | Neural models kept in memory (rule-based ones don't count) |
| `MAX_VIDEO_DURATION_SECONDS` | `600` | Longest accepted video |
| `MAX_UPLOAD_SIZE_MB` | `2048` | Largest accepted file |
| `MAX_INFERENCE_HEIGHT` | `1080` | Taller frames are downscaled for inference |
| `ALLOW_MODEL_DOWNLOAD` | `true` | Download missing weights on first use |
| `RESULTS_RETENTION_DAYS` | `0` | Default age for *Settings → Clean up old results* (0 = keep) |
| `DATABASE_URL` | `sqlite:///database/vision_hub.db` | Any SQLAlchemy URL |
| `STORAGE_DIR` | `storage` | Videos, results, exports |

The frontend dev server proxies `/api` to `http://127.0.0.1:8000`. Override this with `VITE_BACKEND_URL`.

---

## Database

**Setup is automatic.** SQLite with Alembic migrations: the API and the worker both apply migrations at startup, so there is nothing to run by hand.

**Tables:**

| Table | Holds |
|---|---|
| `videos` | Uploaded videos and their metadata |
| `vision_models` | Model catalogue, synced from the plugins at startup |
| `analysis_jobs` | Analyses and their status |
| `analysis_job_models` | Each model in a job: version, weight hash, configuration, status, time |
| `tracked_persons` | People found by tracking |
| `activity_segments` | Activity time ranges per person |
| `frame_stats` | People count per processed frame |
| `model_benchmarks` | Measured speed per model on this machine |

Per-frame detections are **not** stored in the database. They live in chunked result files under `storage/results/`.

**Manual commands** (from `backend/`):

```bash
.venv/bin/alembic upgrade head                                   # apply migrations
.venv/bin/alembic revision --autogenerate -m "describe change"   # after changing database_models.py
```

**Reset everything:** stop the app, then delete `backend/database/vision_hub.db*` and the contents of `backend/storage/*/`.

---

## Running the app

### One command

Starts the API, the worker and the frontend; Ctrl+C stops all three.

```bash
cd vision-hub
./scripts/dev.sh
```

- App: http://localhost:5173
- API docs: http://localhost:8000/docs

Logs also go to `logs/api.log`, `logs/worker.log` and `logs/web.log`.

### Or in three terminals

```bash
# 1. API
cd vision-hub/backend && source .venv/bin/activate
uvicorn app.main:app --port 8000

# 2. Worker (runs the analyses)
cd vision-hub/backend && source .venv/bin/activate
python -m app.workers.analysis_worker

# 3. Frontend
cd vision-hub/frontend && npm run dev
```

The header shows **Worker online / offline**. If the worker isn't running, jobs wait in the queue. Stopping the worker with Ctrl+C marks a running job as interrupted (failed), and you can start it again with *Run again*.

---

## Testing with sample videos

1. **OpenCV's pedestrian clip**: many people walking, 80 s, DivX AVI, so it also tests the playback copy.
   ```bash
   curl -L -o vtest.avi https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/vtest.avi
   ```
2. **Free stock footage**: search "walking", "running", "jumping", "sitting" or "people" on [pexels.com/videos](https://www.pexels.com/videos/) or [pixabay.com/videos](https://pixabay.com/videos/). Download at 720p or 1080p to keep CPU time low.

Then:
1. *Upload Video* → drop the file and wait for **Ready**.
2. *Analyze this video* → tick **Activity Recognition (Pose-based)**. Pose and Tracking are added automatically. Optionally tick **X-CLIP** to compare.
3. Optionally set a frame interval of 2 to halve the time, then **Start analysis**.
4. On the results page, play the video and toggle overlays. Click timeline segments to jump to them.

---

## Adding a new model

Create `backend/app/vision/plugins/<your_model>/__init__.py`:

```python
from pydantic import BaseModel, Field
from app.vision.base_model import BaseVisionModel, ModelSpec, WeightInfo

class MyConfig(BaseModel):
    threshold: float = Field(0.5, ge=0, le=1, description="Shown in the generated form")

class MyModel(BaseVisionModel):
    spec = ModelSpec(
        model_id="vehicle_detection", name="Vehicle Detection", category="vehicles", version="1.0.0",
        description="…", license="…", kind="frame",
        requires=[], produces=["vehicle_detections"],
        weights=[WeightInfo(name="my_weights.pt", source="https://…", size_mb=12)],
        config_schema=MyConfig, default_seconds_per_frame=0.05,
    )

    def load(self, device):                       # import heavy libraries here, not at module level
        ...
        super().load(device)

    def process_frame(self, frame, ctx, upstream):  # frame.image is BGR; upstream has earlier models' outputs
        return {"vehicle_detections": [...]}        # JSON-serialisable

PLUGIN = MyModel
```

Restart the API and worker. The model then:
- appears in the library
- gets a settings form generated from `MyConfig`
- can be combined with any other model
- has its outputs stored in chunked result files

Optional hooks:

| Hook | Purpose |
|---|---|
| `kind="post"` + `process_results(reader, ctx)` | Models that work on the stored results of the whole video |
| `kind="clip"` + `finish(ctx)` | Models that buffer frames and output per window |
| `relative_cost(config)` | Lets runtime estimates scale with settings |
| `advice(config, video)` | Shows tips before a job starts |
| `weight_hashes(config)` | Records exactly which weights were used |
| `ModelSpec.priority` | Picks the default provider when several models produce the same data |

Rules a plugin must follow:
- Never read the video file itself.
- Never write to the database.
- Keep per-job state in `ctx.state`.
- Measure time in seconds (`frame.timestamp`), not frames.

To show a new data type on the canvas or in charts, extend the overlay or analytics code. Storage and execution need no changes.

---

## API

Interactive docs are at http://localhost:8000/docs.

| Method & path | Purpose |
|---|---|
| `POST /api/videos/upload` | Upload (multipart `file`, optional `allow_duplicate`) |
| `GET /api/videos` · `GET /api/videos/{id}` · `DELETE /api/videos/{id}` | Library |
| `GET /api/videos/{id}/stream` · `/thumbnail` · `/download` | Playback (range requests), thumbnail, original |
| `GET /api/models` · `GET /api/models/{id}` · `GET /api/models/{id}/configuration` | Model library, JSON Schema + defaults |
| `POST /api/analysis/plan` | Resolve pipeline, validate configs, estimate runtime |
| `POST /api/analysis/start` | Queue an analysis |
| `GET /api/analysis` · `GET /api/analysis/{id}` | Jobs |
| `GET /api/analysis/{id}/progress` | **Server-Sent Events** progress stream |
| `GET /api/analysis/{id}/status` | Progress as plain JSON (polling fallback) |
| `POST /api/analysis/{id}/cancel` · `DELETE /api/analysis/{id}` | Cancel, delete |
| `GET /api/analysis/{id}/results` | Summary analytics |
| `GET /api/analysis/{id}/frames?start=&end=` | Per-frame overlay data (≤ 60 s per request) |
| `GET /api/analysis/{id}/persons` · `/activities` | Tracked people, activity segments |
| `GET /api/analysis/{id}/annotated-video` | Annotated MP4 (`?download=true`) |
| `GET /api/dashboard` · `GET /api/system` · `POST /api/system/cleanup?days=N` | Dashboard, system info, cleanup |

---

## Tests

```bash
cd vision-hub/backend
.venv/bin/python -m pytest -q
```

What the 55 tests cover:
- planner rules
- posture geometry
- activity features: walking, walking with the camera following, standing, running, sitting, lying, jumping, falling
- smoothing and segments
- the ByteTrack adapter, which guards against changes to the internal Ultralytics API
- chunked storage, including truncated files
- the executor: single pass, post models, failure isolation, cancellation, rendering
- the full API with the worker running

How they run:
- Tests use **fake plugins and a generated video** and never download anything.
- `test_real_models.py` runs the real YOLO pipeline only when its weights are already present.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Worker offline", jobs stay queued | Start the worker (`./scripts/dev.sh` or `python -m app.workers.analysis_worker`) |
| First X-CLIP run is slow | It downloads ~790 MB once. Pre-download with `scripts/download_weights.py` |
| "Cannot reach the backend" | Start the API on port 8000 |
| Analysis too slow | Raise the frame interval (2–3), set the pose detection size to 640 if people are large in the frame, use YOLO11n, skip X-CLIP |
| People are missed (small or far away) | Set the pose model's detection resolution to 1280 |
| Many short tracks / ID switches | Lower the frame interval; raise tracking's `track_buffer_seconds` |
| Too many `uncertain` activities | Lower the activity confidence threshold, or check that people's legs are visible |
| VS Code can't find packages | Select the interpreter `backend/.venv/bin/python` |
| After moving the project folder | Recreate `backend/.venv` (virtual environments store absolute paths) |

---

## Scaling later

The SQLite queue sits behind the `JobQueue` interface (`app/workers/job_queue.py`). To move to Redis or Celery, implement `enqueue` / `claim` / `heartbeat` / `position` and run more workers; the executor and API stay unchanged. To use PostgreSQL, set `DATABASE_URL`.

Planned model categories: vehicles, traffic, objects, segmentation, OCR, depth, gestures, defects and scenes. Each plugs in as another package under `plugins/`.
