# Know Your Focus (KYF)

Know Your Focus measures the time at your workstation. It reports your focused time, your phone use, your uncertain time, and your away time.

A local camera supplies the images. All frame processing stays on your computer.

The application combines person, phone, face, hand, and head-direction signals. It uses MediaPipe Tasks and local model files.

See [PRODUCT_SPEC.md](PRODUCT_SPEC.md) for the complete feature and edge-case specification.

## Current features

- The application captures one low-resolution frame each second.
- The application keeps no frame queue and stores no camera images by default.
- EfficientDet-Lite0 INT8 detects people and mobile phones.
- Face Landmarker estimates head pitch.
- Hand Landmarker associates a phone with a nearby hand.
- The classifier requires a phone near at least one detected hand.
- Head direction changes the confidence and reason. It does not block hand-held phone detection.
- A diagnostic window shows the frame, detector boxes, hand points, and missing evidence.
- An away policy delays `AWAY` classification.
- A rolling window prevents one-frame status changes.
- System idle detection stops camera work during user inactivity.
- The desktop window has start, pause, timed pause, calibration, and preview controls.
- The Ubuntu window uses GTK 4 and Libadwaita through the Rust `gtk4-rs` bindings.
- The interfaces use one local JSON protocol and one shared Python tracking engine.
- The application shows focused active time and classified coverage.
- JSON Lines files store status transitions.
- JSON files store daily summaries.
- Each tracking session has a unique identifier and a JSON summary.
- The interface shows detailed KPI values for the current session.
- An optional toggle saves annotated inference frames for model analysis.
- Local midnight splits durations between the correct daily files.
- A process lock prevents two trackers from writing to one data directory.
- Local history has a retention limit and a confirmed deletion action.

## Install a desktop package

The release supports these systems:

- Ubuntu 24.04 on AMD64.
- macOS 13 or a later version on Apple Silicon.

Download the package and its checksum from the GitHub release.

On Ubuntu, install the `.deb` file:

```bash
sudo apt install ./know-your-focus_1.0.0_amd64.deb
```

Open **Know Your Focus** from the application menu.

On macOS, open the `.dmg` file. Move **Know Your Focus** to the Applications folder.

The application starts in a paused state. Select **Download models** before the first tracking session.

The first model download is about `16 MB`. Tracking does not download models.

The macOS release is signed and notarized. Manual workflow builds can create an unsigned test package.

See [docs/RELEASING.md](docs/RELEASING.md) for package build and release instructions.

## Development setup

Python 3.10 or a later version is necessary. Rust 1.92 is necessary for the desktop interface.

On Ubuntu 24.04, install the desktop build libraries:

```bash
sudo apt install build-essential pkg-config libgtk-4-dev libadwaita-1-dev
```

On macOS, install the desktop build libraries:

```bash
brew install gtk4 libadwaita
```

Install the Rust toolchain:

```bash
rustup toolchain install 1.92.0
```

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
   .venv/bin/kyf download-models
   ```

4. Create a local configuration.

   ```bash
   .venv/bin/kyf init-config --path configuration.json
   ```

5. Build the GTK desktop interface.

   ```bash
   cargo build --manifest-path desktop/Cargo.toml
   ```

6. Start the desktop application.

   ```bash
   .venv/bin/kyf app --config configuration.json
   ```

The Rust process shows the interface. A private JSON Lines connection links it to the Python tracking engine.

To start only the tracking engine, run this command:

```bash
.venv/bin/kyf run --config configuration.json
```

Press `Ctrl+C` to stop the tracking engine.

Use a short run to make sure that the camera works:

```bash
.venv/bin/kyf run --config configuration.json --duration 10
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

Make sure that the Rust frontend passes its checks:

```bash
cargo fmt --manifest-path desktop/Cargo.toml --check
cargo clippy --locked --manifest-path desktop/Cargo.toml -- -D warnings
```

Measure model speed and peak memory without a camera:

```bash
.venv/bin/kyf benchmark --config configuration.json --iterations 10
```

Show the live diagnostic window:

```bash
.venv/bin/kyf preview --config configuration.json
```

The preview requests `1280x720` at `60 FPS`. It runs inference on smaller frames in a background thread.

The side panel shows the measured display rate and inference latency. The camera can supply a lower rate than the requested rate.

The preview sets camera zoom to `0`. This value gives the widest view on supported cameras.

The zoom setting cannot increase the physical field of view of the camera lens.

The preview does not save frames or write session logs. To close it, press `Q` or `Esc`.

Override the phone threshold for a detection experiment:

```bash
.venv/bin/kyf preview --config configuration.json --score-threshold 0.15
```

Set different preview and inference rates:

```bash
.venv/bin/kyf preview --display-fps 60 --inference-fps 10
```

Set the widest camera view explicitly:

```bash
.venv/bin/kyf preview --zoom 0
```

## Data

The default data directory uses `XDG_DATA_HOME` on Linux. The fallback path is `~/.local/share/know-your-focus`.

The application writes these files:

```text
events-YYYY-MM-DD.jsonl
summary-YYYY-MM-DD.json
sessions/
  SESSION_ID/
    summary.json
```

The event file stores state changes and durations. The summary file contains totals that the application rebuilds from valid event records.

Each session summary contains all status durations, KPI values, versions, and final classification details.

Diagnostic output is disabled by default. To save sampled images and an evidence manifest, select **Save diagnostic output** before a session.

Diagnostic images can show the user and the room. The application stores these images locally and limits each session to `3600` images.

## Models

The application downloads approximately `16 MB` of model files. The default model directory is `~/.cache/know-your-focus/models`.

The download command makes sure that each model matches a pinned SHA-256 value. Normal application startup never downloads a model.

## Detection plan

The runtime uses a detector interface. The default adapter uses three MediaPipe tasks.

The object detector runs first. The hand model runs only after the object detector finds a phone.

The application keeps the OpenCV frontal-face adapter as a fallback. To use it, set `detector_backend` to `opencv_face`.

The console output and event log include head pitch and evidence counts. Use these values to tune the head-pitch configuration.

See [docs/DETECTOR_STRATEGY.md](docs/DETECTOR_STRATEGY.md) for the classifier rules and Ultralytics fallback.

See [docs/BENCHMARKS.md](docs/BENCHMARKS.md) for the first Ubuntu measurement.

See [docs/METRICS.md](docs/METRICS.md) for metric definitions and evaluation input.

## Release limits

- The package uses about `400 MB` after installation.
- The MediaPipe process used `301-309 MB` in the first memory benchmark.
- The first detector does not meet the original `150 MB` memory goal.
- Phone-use precision does not have a real-world baseline yet.
- The application does not have a tray icon or a menu-bar icon yet.
- The macOS package supports Apple Silicon only.

Version `1.0.0` is the first release. Do not describe its classifications as measured accuracy, because there is no real-world baseline yet.

## Privacy

- The application does not send frames to a server.
- The application does not save camera images by default.
- The application saves sampled diagnostic images only after explicit consent.
- The application does not use identity recognition.
- The application does not download models during tracking.
- The application shows errors instead of inventing a productivity label.

Do not use this application for employment or performance decisions.
