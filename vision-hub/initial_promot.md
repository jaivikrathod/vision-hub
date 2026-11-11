# Project: Local AI-Powered Human Detection & Multi-Person Tracking System

## 1. Project Overview

Build a complete, locally running AI-powered video analysis application that detects and tracks every human present in an uploaded video.

The application should allow users to upload a video, process it using computer vision models, identify every person, assign a unique tracking ID to each person, draw a green bounding box around each detected person, and generate a processed video that users can preview and download.

The application must run entirely on the user's local laptop. Do not depend on cloud APIs or external AI services.

This is the first version of a larger computer vision platform. Design the architecture so that future features such as human activity recognition, movement analysis, people counting, and behavioral analysis can be added without rewriting the existing application.

## 2. Technology Stack

### Backend
- Python 3.11+
- FastAPI
- Uvicorn
- SQLAlchemy ORM
- SQLite database
- Pydantic
- OpenCV
- Ultralytics YOLO11
- ByteTrack for multi-object tracking
- NumPy
- FFmpeg for video encoding where necessary

### Frontend
- React 18+
- Vite
- JavaScript or TypeScript
- Tailwind CSS
- Axios
- React Router
- React Player or native HTML5 video player
- Lucide React icons

Do not use Flask.
Prefer FastAPI over Django for this project.

### Database
Use SQLite for the initial implementation.

Database file:
`database/app.db`

Use SQLAlchemy models and Alembic migrations so that SQLite can later be replaced with MySQL with minimal changes.

## 3. Core Application Workflow

The complete workflow should be:

1. User opens the application.
2. User uploads a video.
3. Backend validates the video.
4. Original video is stored locally.
5. A video processing task is created.
6. The backend extracts frames using OpenCV.
7. YOLO detects all humans in every processed frame.
8. ByteTrack tracks the detected people across consecutive frames.
9. Every person receives a unique tracking ID.
10. Draw a green bounding box around each detected person.
11. Display the tracking ID above the bounding box.
12. Generate an annotated output video.
13. Store processing statistics in SQLite.
14. User can preview and download the processed video.

## 4. Computer Vision Requirements

### Human Detection

Use a pretrained YOLO11 model.

Initially use:
`yolo11n.pt`

Use the COCO person class:
`class_id = 0`

Only detect humans in the first version.

The detection system should support:
- Multiple people in the same frame.
- People walking.
- People standing.
- People sitting.
- People entering and leaving the camera view.
- People moving in different directions.
- People appearing at different distances from the camera.

Provide configurable confidence thresholds.

Default confidence:
0.40

### Multi-Person Tracking

Use ByteTrack through the Ultralytics tracking API.

Example:

```python
results = model.track(
    frame,
    persist=True,
    classes=[0],
    tracker="bytetrack.yaml",
    conf=0.40
)
```

Important requirements:

- Maintain tracking IDs across consecutive frames.
- Do not generate a new ID for every frame.
- Handle temporary detection loss.
- Handle people crossing paths.
- Handle multiple people appearing simultaneously.
- Keep tracking state consistent throughout a video.
- Track IDs should be unique within each video.

Do not use facial recognition or identify people by their real-world identities.

### Bounding Box Visualization

For each detected person:

- Draw a green rectangular bounding box.
- Display the tracking ID.
- Optionally display detection confidence.
- Use readable labels.
- Ensure bounding boxes remain aligned with people.

Suggested visualization:

```text
+-----------------------+
| Person #1             |
|                       |
|       HUMAN           |
|                       |
+-----------------------+
```

Use green color:
`(0, 255, 0)`

Allow visualization settings to be configurable.

## 5. Video Processing Engine

Create a separate video processing service.

Responsibilities:

- Read uploaded video.
- Extract frames.
- Process frames using YOLO.
- Track people using ByteTrack.
- Annotate frames.
- Generate the final output video.
- Calculate processing statistics.
- Report progress to the API.

Support:
- MP4
- AVI
- MOV
- MKV, where supported by the installed FFmpeg/OpenCV codecs.

Extract:
- Video duration.
- FPS.
- Width.
- Height.
- Total frame count.

Implement:
- Frame-by-frame processing.
- Configurable frame skipping.
- Configurable detection confidence.
- Proper resource cleanup.
- Error handling.
- Temporary file cleanup.

Use a video writer with an appropriate codec, preferably H.264 where supported. Provide a compatible fallback if necessary.

Do not load the entire video into RAM.

## 6. Application Dashboard

Create a modern, professional dashboard.

Design inspiration:
- Modern AI analytics dashboard.
- Dark/light mode.
- Clean interface.
- Responsive layout.
- Minimal unnecessary elements.

### Dashboard Layout

Sidebar:

- Dashboard
- Video Analysis
- Processing History
- Settings
- About

Main Dashboard:

Display statistics:

- Total videos processed.
- Total unique tracking IDs across completed videos.
- Total processing time.
- Recently processed videos.

### Video Upload Page

Requirements:

- Drag-and-drop video upload.
- Browse files button.
- Display selected filename.
- Display video size.
- Display video duration if available.
- Show upload progress.
- Validate supported formats.
- Show upload errors.

Allow users to configure:

- Detection confidence.
- Frame skipping.
- Bounding box visibility.
- Tracking ID visibility.
- Confidence label visibility.

Default configuration should work without requiring user input.

### Processing Page

Display:

- Uploaded video information.
- Processing status.
- Processing percentage.
- Frames processed.
- Total frames.
- Detected people count.
- Processing speed in FPS.
- Estimated remaining time, when available.

Show processing states:

- Uploaded
- Queued
- Processing
- Completed
- Failed

Provide a live processing progress indicator.

### Results Page

After processing, display:

1. Original video preview.
2. Processed video preview.
3. Total unique people detected.
4. Total frames processed.
5. Average processing FPS.
6. Processing duration.
7. Detection statistics.

Provide a download button for the annotated video.

Also provide an option to download detection statistics as CSV.

## 7. Database Design

Use SQLAlchemy with SQLite.

Create the following tables.

### Table: videos

Fields:

- id
- original_filename
- stored_filename
- original_video_path
- processed_video_path
- file_size
- duration
- fps
- width
- height
- total_frames
- processing_status
- processing_percentage
- total_unique_persons
- frames_processed
- processing_time
- created_at
- updated_at

### Table: detection_sessions

Fields:

- id
- video_id
- model_name
- tracker_name
- confidence_threshold
- frame_skip
- total_detections
- total_unique_persons
- total_frames_processed
- average_processing_fps
- processing_started_at
- processing_completed_at
- created_at

### Table: tracked_persons

Fields:

- id
- video_id
- tracking_id
- first_detected_frame
- last_detected_frame
- total_detected_frames
- first_detected_timestamp
- last_detected_timestamp
- average_confidence
- created_at

Add proper foreign keys and indexes.

A tracking ID should be unique within a video, not globally across all videos.

### Table: detection_events

Fields:

- id
- video_id
- tracked_person_id
- frame_number
- timestamp_seconds
- x1
- y1
- x2
- y2
- confidence
- created_at

Store detection events so that future analytics can be implemented without reprocessing the video.

## 8. Backend API Architecture

Use REST APIs.

### Video APIs

POST `/api/videos/upload`

Upload a video and create a video record.

GET `/api/videos`

Return video history with pagination.

GET `/api/videos/{video_id}`

Return video details and processing status.

DELETE `/api/videos/{video_id}`

Delete the video record and associated local files safely.

### Processing APIs

POST `/api/videos/{video_id}/process`

Start processing a video.

GET `/api/videos/{video_id}/progress`

Return processing progress.

POST `/api/videos/{video_id}/cancel`

Cancel a running processing task safely.

### Results APIs

GET `/api/videos/{video_id}/results`

Return tracking statistics.

GET `/api/videos/{video_id}/original

Serve the original video.

GET `/api/videos/{video_id}/processed`

Serve the processed video.

GET `/api/videos/{video_id}/export/csv`

Export detection statistics.

### Dashboard APIs

GET `/api/dashboard/stats`

Return:

- Total videos.
- Completed videos.
- Failed videos.
- Total unique tracking records.
- Recent processing history.

## 9. Processing Architecture

Do not run long-running video processing directly inside the HTTP request.

Implement a background processing architecture.

For the initial local version:

- Use Python threading or a controlled background worker.
- Maintain a processing task registry.
- Ensure that multiple tasks do not consume unlimited CPU or RAM.
- Allow one processing job at a time by default.
- Support progress updates.
- Support task cancellation.
- Persist processing status in SQLite.
- Recover or mark interrupted tasks appropriately when the application restarts.

Do not introduce Celery, Redis, RabbitMQ, or other external infrastructure in version one.

Use WebSocket or Server-Sent Events (SSE) for real-time progress updates. Prefer SSE for the initial implementation.

## 10. Project Structure

Create a clean, modular project structure.

```text
human-tracking-system/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   │
│   │   ├── api/
│   │   │   ├── videos.py
│   │   │   ├── processing.py
│   │   │   ├── results.py
│   │   │   └── dashboard.py
│   │   │
│   │   ├── models/
│   │   │   ├── video.py
│   │   │   ├── detection_session.py
│   │   │   ├── tracked_person.py
│   │   │   └── detection_event.py
│   │   │
│   │   ├── schemas/
│   │   ├── services/
│   │   │   ├── video_service.py
│   │   │   ├── detection_service.py
│   │   │   ├── tracking_service.py
│   │   │   ├── video_processing_service.py
│   │   │   └── analytics_service.py
│   │   │
│   │   ├── core/
│   │   │   ├── database.py
│   │   │   ├── security.py
│   │   │   └── exceptions.py
│   │   │
│   │   └── workers/
│   │       └── video_worker.py
│   │
│   ├── uploads/
│   ├── processed/
│   ├── models/
│   ├── database/
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── pages/
│   │   ├── layouts/
│   │   ├── services/
│   │   ├── hooks/
│   │   ├── context/
│   │   ├── utils/
│   │   ├── App.jsx
│   │   └── main.jsx
│   │
│   ├── package.json
│   └── vite.config.js
│
├── README.md
└── .gitignore
```

## 11. Performance Optimization

The application must work on normal laptops without requiring an NVIDIA GPU.

Implement:

- Automatic CPU/GPU device selection.
- Use CUDA when a compatible NVIDIA GPU is available.
- Use CPU otherwise.
- Allow model selection between YOLO11n and YOLO11s.
- Allow configurable frame skipping.
- Avoid unnecessary frame copies.
- Process videos in batches only where appropriate.
- Avoid storing all frames in memory.
- Display actual processing FPS.

Do not assume GPU availability.

The application should remain functional with CPU-only processing.

## 12. Error Handling

Handle the following cases:

- Unsupported video format.
- Corrupted video.
- Empty video.
- Video decoding errors.
- Missing model weights.
- Insufficient disk space.
- Processing failure.
- User cancellation.
- Application restart during processing.
- Codec incompatibility.
- Duplicate uploads.

Display meaningful error messages in the frontend.

Log detailed errors in the backend.

## 13. Security and Local Privacy

- Keep all uploaded videos on the local machine.
- Do not upload videos to external services.
- Do not call external AI APIs.
- Validate uploaded file extensions and actual file content.
- Generate safe internal filenames.
- Prevent path traversal.
- Restrict file access to application-managed directories.
- Do not expose arbitrary local filesystem paths through APIs.

## 14. Future Expansion Architecture

Design the application so the following features can be added later.

Do not implement them in version one, but avoid architecture decisions that would prevent them.

### Phase 2: Human Activity Recognition

- Walking detection.
- Running detection.
- Standing detection.
- Sitting detection.
- Falling detection.
- Jumping detection.

### Phase 3: Movement Analytics

- Person movement trajectories.
- Direction detection.
- Entry and exit counting.
- Time spent in an area.
- Movement heatmaps.
- Speed estimation.

### Phase 4: Advanced Computer Vision

- Human segmentation.
- Green outline around the entire body instead of rectangular bounding boxes.
- Pose estimation.
- Multi-camera tracking.
- Re-identification across temporary occlusions and camera changes.

### Phase 5: Advanced Analytics Dashboard

- Person-wise activity timelines.
- Frame-by-frame tracking history.
- People counting graphs.
- Movement heatmaps.
- Activity distribution charts.

Important: Basic ByteTrack IDs are video-local tracking identifiers, not guaranteed real-world identities. Avoid claiming that IDs remain reliable after long occlusions or across separate videos.

## 15. Development Instructions

Build this project end to end.

Follow these rules:

1. First create the backend project and install dependencies.
2. Implement SQLite database configuration.
3. Create database models and migrations.
4. Implement video upload APIs.
5. Implement YOLO human detection.
6. Integrate ByteTrack.
7. Implement annotated video generation.
8. Implement background processing and progress tracking.
9. Implement results and CSV export APIs.
10. Build the React dashboard.
11. Integrate frontend and backend.
12. Test the entire workflow using a sample video.
13. Add proper error handling.
14. Write complete setup documentation.

Do not generate placeholder functions or fake API responses.

Do not skip backend implementation and focus only on frontend UI.

Do not hardcode processing results.

All statistics must come from actual video processing.

Keep the code modular, readable, maintainable, and production-conscious.

Provide exact installation and execution commands for Ubuntu/Linux.

The final application must be runnable locally with:

Backend:
`uvicorn app.main:app --reload --port 8000`

Frontend:
`npm run dev`

## 16. Definition of Done

The project is complete only when:

- A user can upload an actual video.
- The backend can process it using YOLO.
- Every detected person receives a tracking ID.
- IDs persist across consecutive frames where tracking is successful.
- Green bounding boxes appear around detected people.
- The processed video can be played in the browser.
- The processed video can be downloaded.
- Unique tracking statistics are stored in SQLite.
- Processing progress is displayed in real time.
- The application works without cloud APIs.
- The application works on CPU-only laptops.
- The README contains complete setup instructions.

Build the complete working application, not just a demonstration or proof of concept.