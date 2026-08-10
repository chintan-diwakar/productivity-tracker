# Desk Focus Tracker

Desk Focus Tracker estimates desk-focus time from a webcam. All frame processing stays on the local computer.

The prototype combines person, phone, face, hand, and head-direction signals. It uses MediaPipe Tasks and local model files.

See [PRODUCT_SPEC.md](PRODUCT_SPEC.md) for the complete feature and edge-case specification.

## Current features

- The application captures one low-resolution frame each second.
- The application keeps no frame queue and stores no camera images.
- EfficientDet-Lite0 INT8 detects people and mobile phones.
- Face Landmarker estimates head pitch.
- Hand Landmarker associates a phone with a nearby hand.
- The classifier requires phone, hand, and downward-head evidence for phone use.
- An away policy delays `AWAY` classification.
- A rolling window prevents one-frame status changes.
- JSON Lines files store status transitions.
- JSON files store daily summaries.
- Unit tests cover configuration, model downloads, classification, policies, smoothing, and storage.

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

The object detector runs first. The hand model runs only when the object detector finds a phone.

The application retains the OpenCV frontal-face adapter as a fallback. Set `detector_backend` to `opencv_face` to use it.

The console output and event log include head pitch and evidence counts. Use these values to tune the head-pitch configuration.

See [docs/DETECTOR_STRATEGY.md](docs/DETECTOR_STRATEGY.md) for the classifier rules and Ultralytics fallback.

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for the first Ubuntu measurement.

## Privacy

- The application does not send frames to a server.
- The application does not save raw frames.
- The application does not use identity recognition.
- The application does not download models during tracking.
- The application shows errors instead of inventing a productivity label.

This project is an early prototype. Do not use its output for employment or performance decisions.
