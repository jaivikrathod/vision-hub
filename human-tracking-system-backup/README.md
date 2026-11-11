# Human Detection & Multi-Person Tracking System

A locally running web application that detects every person in an uploaded video with **YOLO11**, tracks them across frames with **ByteTrack**, draws a **green bounding box with a tracking ID** around each person, and produces an annotated video you can preview and download.

Everything runs on your own computer. Videos are never uploaded anywhere, and no cloud or external AI APIs are used. The app works on CPU-only laptops and uses an NVIDIA GPU automatically if one is available.

---

## Features

- Upload by drag-and-drop or file browser (MP4, AVI, MOV, MKV), with upload progress and validation of both the extension and the actual file content.
- YOLO11n (default) or YOLO11s person detection (COCO class 0), with a configurable confidence threshold (default **0.40**).
- ByteTrack multi-object tracking via the Ultralytics tracking API (`persist=True`). IDs stay stable across consecutive frames, short detection gaps, and people crossing paths.
- Annotated **H.264 MP4** output that plays in any browser. The original audio track is kept.
- Configurable frame skipping, and toggles for boxes, ID labels, and confidence labels.
- Background worker with a job queue (one job at a time by default), **live progress over Server-Sent Events**, cancellation, and recovery after a restart.
- Results page: side-by-side original and processed players, unique-people count, FPS, processing time, detection statistics, a people-over-time chart, and a per-person table.
- Downloads: the annotated video, a per-person statistics CSV, and a raw per-frame detection-events CSV.
- Dashboard with totals and recent videos; paginated, searchable history; dark/light mode; responsive layout.
- SQLite through SQLAlchemy and Alembic migrations, so you can switch to MySQL or PostgreSQL by changing `DATABASE_URL`.

---

## Requirements

| Component | Version |
|-----------|---------|
| OS | Ubuntu 22.04 / 24.04 (other Linux distros work similarly) |
| Python | **3.11+** (tested with 3.12) |
| Node.js | **20.19+ or 22.12+** (required by Vite) |
| Disk | ~1.5 GB for the Python environment (CPU PyTorch) + space for videos |
| GPU | Optional. NVIDIA + CUDA drivers are used automatically when present |

You don't need to install FFmpeg on the system. A static FFmpeg binary comes with the `imageio-ffmpeg` Python package. If a system `ffmpeg` is on your `PATH`, it is used instead.

---

## Installation (Ubuntu / Linux)

### 1. System packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip curl
# Node.js 22 LTS (skip if `node --version` already shows >= 20.19)
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs
```

### 2. Backend

```bash
cd human-tracking-system/backend

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# Install PyTorch first. Pick ONE:
#   a) CPU-only laptop (smaller download, recommended if you have no NVIDIA GPU)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
#   b) NVIDIA GPU (CUDA 12.4 wheels; see https://pytorch.org for other versions)
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124

pip install -r requirements.txt

# Optional: customise settings
cp .env.example .env
```

**Model weights.** The first time a model is used, its official weights (`yolo11n.pt` ≈ 5.4 MB, `yolo11s.pt` ≈ 19 MB) are downloaded once into `backend/models/`. After that, everything works offline. To prepare an offline machine ahead of time:

```bash
cd backend/models
curl -LO https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt
curl -LO https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11s.pt
```

Then set `ALLOW_MODEL_DOWNLOAD=false` in `.env` if you want to forbid any download.

### 3. Frontend

```bash
cd human-tracking-system/frontend
npm install
```

---

## Running

Open two terminals.

**Terminal 1: backend** (from `backend/`)

```bash
cd human-tracking-system/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

On startup the backend creates the directories, applies database migrations (`database/app.db`), and starts the background worker. The API docs are at <http://localhost:8000/docs>.

**Terminal 2: frontend** (from `frontend/`)

```bash
cd human-tracking-system/frontend
npm run dev
```

Open **<http://localhost:5173>**. The Vite dev server forwards `/api` requests to the backend on port 8000.

### Quick test with a sample video

```bash
curl -L -o /tmp/people.mp4 https://github.com/intel-iot-devkit/sample-videos/raw/master/people-detection.mp4
```

Upload `/tmp/people.mp4` on the **Video Analysis** page. On a typical 12-core laptop CPU, YOLO11n processes this 768×432 clip at about **10–12 FPS** (about 30 FPS with frame skip = 2) and finds 8 tracked people.

### Running the tests

```bash
cd backend && source .venv/bin/activate
pytest -q
```

The tests use a temporary database and storage. The end-to-end test runs real YOLO and ByteTrack processing if `models/yolo11n.pt` exists.

### Production-style frontend build (optional)

```bash
cd frontend
npm run build          # outputs frontend/dist/
```

Serve `dist/` with any static web server that forwards `/api` to the backend. Alternatively, set `VITE_API_BASE_URL=http://localhost:8000` before building and add the frontend's origin to the backend's `CORS_ORIGINS`.

---

## How it works

```
Upload ──► validate (extension + magic bytes + OpenCV decode) ──► uploads/<uuid>.mp4 + DB row
   │
POST /process ──► DetectionSession row ──► job queue ──► worker thread
                                                         │
     for each frame (streamed, never fully in RAM):      ▼
       OpenCV read ─► YOLO11 (class 0) ─► ByteTrack IDs ─► draw boxes ─► FFmpeg (H.264) pipe
                                │
                                └─► tracked_persons / detection_events (batched inserts)
                                                         │
     progress (in-memory registry + periodic DB writes) ─► SSE ─► React progress page
                                                         ▼
                                   processed/<uuid>_tracked.mp4  ─► preview / download / CSV
```

- **Frame skipping.** With `frame_skip = N`, YOLO and ByteTrack run on 1 of every N+1 frames. Skipped frames reuse the last boxes, so the output keeps the original length and FPS.
- **Device selection.** `DEVICE=auto` uses `cuda:0` when `torch.cuda.is_available()` and otherwise uses CPU.
- **Video encoding.** Raw frames are piped to FFmpeg/libx264 (`yuv420p`, `+faststart`), and the original audio is muxed back in. If FFmpeg is unavailable, the app falls back to OpenCV `avc1` or `mp4v`.
- **One model instance per job.** Ultralytics stores tracker state on the model object, so each video gets a fresh tracker and IDs never leak between videos.
- **Restart safety.** Jobs that were queued or running when the app stopped are marked *failed – interrupted* on the next startup. Their partial results and temporary files are removed, and you can start them again from the UI.
- **Privacy.** Ultralytics usage analytics are disabled at runtime. The only network access is the optional one-time weight download.

### About tracking IDs

ByteTrack IDs are **video-local identifiers**, not identities:

- They persist while a person is tracked and survive short occlusions (by default up to 30 analyzed frames).
- A person may receive a **new ID** after a long occlusion or after leaving and re-entering the frame.
- IDs are unique within one video only. ID numbers may skip values, because ByteTrack also uses up IDs for tentative tracks that are never confirmed.
- The app performs no facial recognition or identification of real people.

---

## Project structure

```
human-tracking-system/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, lifespan (migrations, recovery, worker)
│   │   ├── config.py               # Settings (env / .env)
│   │   ├── api/                    # videos, processing (+SSE), results, dashboard
│   │   ├── models/                 # SQLAlchemy: Video, DetectionSession, TrackedPerson, DetectionEvent
│   │   ├── schemas/                # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── video_service.py            # upload validation, storage, listing, deletion
│   │   │   ├── detection_service.py        # device selection, weight resolution, YOLO loading
│   │   │   ├── tracking_service.py         # ByteTrack wrapper -> PersonDetection
│   │   │   ├── video_processing_service.py # the processing pipeline
│   │   │   └── analytics_service.py        # results, timeline, dashboard, CSV
│   │   ├── vision/                 # annotator (drawing) and video_io (probe, H.264 writer)
│   │   ├── core/                   # database, security (path/file safety), exceptions
│   │   └── workers/video_worker.py # job queue, task registry, cancellation, recovery
│   ├── migrations/                 # Alembic
│   ├── tests/                      # pytest
│   ├── uploads/ processed/ models/ database/ tmp/
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── pages/        # Dashboard, VideoAnalysis, Processing, Results, History, Settings, About
│   │   ├── components/   # UI kit, Dropzone, VideoPlayer, PeopleChart, settings form…
│   │   ├── layouts/      # sidebar layout
│   │   ├── hooks/        # useAsync, useProgressStream (SSE with polling fallback)
│   │   ├── context/      # theme, processing defaults
│   │   ├── services/     # axios API client
│   │   └── utils/
│   ├── package.json
│   └── vite.config.js
├── README.md
└── .gitignore
```

---

## REST API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/videos/upload` | Multipart upload (`file`, optional `allow_duplicate=true`) |
| GET | `/api/videos?page=&page_size=&status=&search=` | Paginated history |
| GET | `/api/videos/{id}` | Video details and status |
| DELETE | `/api/videos/{id}` | Delete the record and its files (rejected while processing) |
| POST | `/api/videos/{id}/process` | Start processing. Body (all optional): `model_name`, `confidence`, `frame_skip`, `show_boxes`, `show_ids`, `show_confidence` |
| GET | `/api/videos/{id}/progress` | Progress snapshot (JSON) |
| GET | `/api/videos/{id}/progress/stream` | Progress as Server-Sent Events |
| POST | `/api/videos/{id}/cancel` | Cancel a queued or running job |
| GET | `/api/videos/{id}/results` | Statistics, per-person data, timeline |
| GET | `/api/videos/{id}/original[?download=true]` | Original video (supports HTTP range requests) |
| GET | `/api/videos/{id}/processed[?download=true]` | Annotated MP4 |
| GET | `/api/videos/{id}/export/csv?type=persons\|events` | CSV export |
| GET | `/api/dashboard/stats` | Dashboard totals and recent videos |
| GET | `/api/system/info` | Device, models, FFmpeg availability, defaults |

Errors return `{"detail": "<message>", "code": "<code>"}` with an appropriate status code: 409 for a duplicate or conflict, 413 for a file that is too large, 415 for an unsupported format, 422 for a corrupted or empty video, and 507 for insufficient disk space.

---

## Database

The tables are `videos`, `detection_sessions`, `tracked_persons` (unique on `(video_id, tracking_id)`), and `detection_events` (one row per person per analyzed frame, indexed on `(video_id, frame_number)`). Foreign keys use `ON DELETE CASCADE`.

Every bounding box is stored, so later features can be computed without reprocessing the video. Examples include trajectories, heatmaps, entry/exit counts, and activity recognition.

To change the schema:

```bash
cd backend && source .venv/bin/activate
alembic revision --autogenerate -m "describe change"
alembic upgrade head      # also applied automatically on startup
```

To switch to MySQL, run `pip install pymysql`, set `DATABASE_URL=mysql+pymysql://user:pass@host/db`, and restart.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Cannot reach the backend` in the UI | Start the backend on port 8000. |
| `Model weights … could not be downloaded` | No internet on first use. Download the `.pt` files manually into `backend/models/` (see above). |
| Original AVI/MKV won't preview | Browsers can't play every codec. The **processed** video is always H.264 MP4 and plays everywhere. Use the download link for the original. |
| Processing is slow | Use YOLO11n, increase frame skipping, or use an NVIDIA GPU with the CUDA PyTorch build. |
| `Not enough free disk space` | Delete old videos in History, or lower `MIN_FREE_DISK_MB`. |
| Job shows *interrupted* after a restart | Expected. Open the video and click **Start processing** again. |
| Port 8000 / 5173 already in use | Stop the other process, or use `--port` for uvicorn. For the frontend, set `VITE_BACKEND_URL` and the Vite port. |

---

## Roadmap (designed for, not implemented in v1)

- Phase 2: activity recognition (walking, running, standing, sitting, falling, jumping)
- Phase 3: trajectories, direction, entry/exit counting, dwell time, heatmaps, speed
- Phase 4: segmentation outlines, pose estimation, multi-camera tracking, re-identification
- Phase 5: per-person timelines, frame-by-frame history, counting graphs, activity charts

New analyzers can work from the stored `detection_events`, or plug into `VideoProcessor` as an extra per-frame step next to the tracker and annotator.
