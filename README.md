# Desk Focus Tracker

Desk Focus Tracker estimates desk-focus time from a webcam. All frame processing stays on the local computer.

The application combines person, phone, face, hand, and head-direction signals. It uses MediaPipe Tasks and local model files.

See [PRODUCT_SPEC.md](PRODUCT_SPEC.md) for the complete feature and edge-case specification.

## Current features

- The application captures one low-resolution frame each second.
- The application keeps no frame queue and stores no camera images.
- EfficientDet-Lite0 INT8 detects people and mobile phones.
- Face Landmarker estimates head pitch.
- Hand Landmarker associates a phone with a nearby hand.
- The classifier requires phone, hand, and downward-head evidence for phone use.
- A diagnostic window shows the frame, detector boxes, hand points, and missing evidence.
- An away policy delays `AWAY` classification.
- A rolling window prevents one-frame status changes.
- System idle detection stops camera work during user inactivity.
- Start, pause, timed pause, calibration, and preview controls are available in a small desktop window.
- The application shows focused active time and classified coverage.
- JSON Lines files store status transitions.
- JSON files store daily summaries.
- Local midnight splits durations between the correct daily files.
- A process lock prevents two trackers from writing to one data directory.
- Local history has a retention limit and a confirmed deletion action.

## Install a desktop package

The first pre-release supports these systems:

- Ubuntu 24.04 on AMD64.
- macOS 13 or a later version on Apple Silicon.

Download the package and its checksum from the GitHub release.

On Ubuntu, install the `.deb` file:

```bash
sudo apt install ./desk-focus-tracker_0.1.0_amd64.deb
```

Open **Desk Focus Tracker** from the application menu.

On macOS, open the `.dmg` file. Move **Desk Focus Tracker** to the Applications folder.

The application starts in a paused state. Select **Download models** before the first tracking session.

The first model download is about `16 MB`. Tracking does not download models.

The macOS release is signed and notarized. Manual workflow builds can create an unsigned test package.

See [docs/RELEASING.md](docs/RELEASING.md) for package build and release instructions.

## Development setup

Python 3.10 or a later version is required.

1. Create a virtual environment.

   ```bash
   python3 -m venv .venv
   ```

2. Install the project and its development dependencies.

   ```bash
   .venv/bin/python -m pip install -e '.[dev]'
   ```

3. Download the pinned MediaPipe models.

   ```bash
   .venv/bin/desk-focus download-models
   ```

4. Create a local configuration.

   ```bash
   .venv/bin/desk-focus init-config --path configuration.json
   ```

5. Start the tracker.

   ```bash
   .venv/bin/desk-focus run --config configuration.json
   ```

6. Press `Ctrl+C` to stop the tracker.

Use a short run to make sure that the camera works:

```bash
.venv/bin/desk-focus run --config configuration.json --duration 10
```

## Tests

Run the standard-library test suite without an installation:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Run the installed development test suite:

```bash
.venv/bin/pytest
```

Measure model speed and peak memory without a camera:

```bash
.venv/bin/desk-focus benchmark --config configuration.json --iterations 10
```

Show the live diagnostic window:

```bash
.venv/bin/desk-focus preview --config configuration.json
```

The preview requests `1280x720` at `60 FPS`. It runs inference on smaller frames in a background thread.

The side panel shows the measured display rate and inference latency. The camera can supply a lower rate than the requested rate.

The preview sets camera zoom to `0`. This value gives the widest view on supported cameras.

The zoom setting cannot increase the physical field of view of the camera lens.

The preview does not save frames or write session logs. Press `Q` or `Esc` to close it.

Use a lower threshold for a phone-detection experiment:

```bash
.venv/bin/desk-focus preview --config configuration.json --score-threshold 0.15
```

Set different preview and inference rates:

```bash
.venv/bin/desk-focus preview --display-fps 60 --inference-fps 10
```

Set the widest camera view explicitly:

```bash
.venv/bin/desk-focus preview --zoom 0
```

## Data

The default data directory follows `XDG_DATA_HOME` on Linux. The fallback path is `~/.local/share/desk-focus-tracker`.

The application writes these files:

```text
events-YYYY-MM-DD.jsonl
summary-YYYY-MM-DD.json
```

The event file stores state changes and durations. The summary file contains totals that the application rebuilds from valid event records.

## Models

The application downloads approximately `16 MB` of model files. The default model directory is `~/.cache/desk-focus-tracker/models`.

The download command verifies each model with a pinned SHA-256 value. Normal application startup never downloads a model.

## Detection plan

The runtime uses a detector interface. The default adapter uses three MediaPipe tasks.

The object detector runs first. The hand model runs only after the object detector finds a phone.

The application retains the OpenCV frontal-face adapter as a fallback. Set `detector_backend` to `opencv_face` to use it.

The console output and event log include head pitch and evidence counts. Use these values to tune the head-pitch configuration.

See [docs/DETECTOR_STRATEGY.md](docs/DETECTOR_STRATEGY.md) for the classifier rules and Ultralytics fallback.

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for the first Ubuntu measurement.

See [docs/METRICS.md](docs/METRICS.md) for metric definitions and evaluation input.

## First-release limits

- The package uses about `400 MB` after installation.
- The MediaPipe process used `301-309 MB` in the first memory benchmark.
- The first detector does not meet the original `150 MB` memory goal.
- Phone-use precision does not have a real-world baseline yet.
- The desktop interface is a small fallback window. It is not a tray icon yet.
- The macOS package supports Apple Silicon only.

Version `0.1.0` is a pre-release for personal testing. Do not describe its classifications as measured accuracy.

## Privacy

- The application does not send frames to a server.
- The application does not save raw frames.
- The application does not use identity recognition.
- The application does not download models during tracking.
- The application shows errors instead of inventing a productivity label.

Do not use this application for employment or performance decisions.
