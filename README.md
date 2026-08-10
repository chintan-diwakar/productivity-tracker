# Desk Focus Tracker

Desk Focus Tracker estimates desk-focus time from a webcam. All frame processing stays on the local computer.

The current prototype detects frontal-face presence. It does not detect phone use or head direction yet.

See [PRODUCT_SPEC.md](PRODUCT_SPEC.md) for the complete feature and edge-case specification.

## Current features

- The application captures one low-resolution frame each second.
- The application keeps no frame queue and stores no camera images.
- An OpenCV detector reports frontal-face presence.
- An away policy delays `AWAY` classification.
- A rolling window prevents one-frame status changes.
- JSON Lines files store status transitions.
- JSON files store daily summaries.
- Unit tests cover configuration, policies, smoothing, and storage.

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

3. Create a local configuration.

   ```bash
   .venv/bin/desk-focus init-config --path configuration.json
   ```

4. Start the tracker.

   ```bash
   .venv/bin/desk-focus run --config configuration.json
   ```

5. Press `Ctrl+C` to stop the tracker.

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

## Data

The default data directory follows `XDG_DATA_HOME` on Linux. The fallback path is `~/.local/share/desk-focus-tracker`.

The application writes these files:

```text
events-YYYY-MM-DD.jsonl
summary-YYYY-MM-DD.json
```

The event file stores state changes and durations. The summary file contains totals that the application rebuilds from valid event records.

## Detection plan

The runtime uses a detector interface. The current adapter uses the frontal-face cascade that OpenCV includes.

The planned phone adapter uses an exported ONNX object model. MediaPipe will provide face landmarks and head direction.

See [docs/DETECTOR_STRATEGY.md](docs/DETECTOR_STRATEGY.md) for the Ultralytics evaluation and license constraints.

## Privacy

- The application does not send frames to a server.
- The application does not save raw frames.
- The application does not use identity recognition.
- The application shows errors instead of inventing a productivity label.

This project is an early prototype. Do not use its output for employment or performance decisions.

