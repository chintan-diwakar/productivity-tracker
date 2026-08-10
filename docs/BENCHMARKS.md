# Prototype Benchmarks

## Reference environment

The first measurement used this environment:

- Ubuntu Linux on x86-64.
- Python `3.14.4`.
- MediaPipe `1.0.0`.
- OpenCV-Contrib `5.0.0.93`.
- A synthetic black frame with a size of `320x240`.
- EfficientDet-Lite0 and Face Landmarker loaded at startup.
- Hand Landmarker loaded only after phone detection.

The benchmark did not activate the webcam.

## Representative result

| Measurement | Result |
| --- | ---: |
| Model load time | About `0.54 s` |
| Mean inference time over five frames | About `46 ms` |
| Peak resident memory | `301-309 MB` |

The prototype meets the `1 FPS` speed goal. It does not meet the `150 MB` memory goal.

## Live preview measurement

The high-quality preview requests `1280x720` at `60 FPS`. A background thread runs inference at `10 FPS`.

| Measurement | Result |
| --- | ---: |
| Camera driver report | `60 FPS` |
| Measured display rate | About `30 FPS` |
| Typical inference time | `48-56 ms` |

The reference EMEET SmartCam Nova 4K delivered about `30 FPS` at both `720p` and `1080p`.

Manual exposure values did not increase the capture rate. A camera with a real `60 FPS` mode is necessary for 60 unique frames each second.

## Memory isolation

| Loaded components | Peak resident memory |
| --- | ---: |
| Python, NumPy, OpenCV, and MediaPipe imports | `192.9 MB` |
| Object Detector | `248.4 MB` |
| Face Landmarker | `229.1 MB` |
| Hand Landmarker | `263.1 MB` |
| Object Detector and Face Landmarker | `274.9 MB` |

The Python MediaPipe package exceeds the memory goal before all three tasks load.

## Reproduction

1. Download the model files.

   ```bash
   .venv/bin/desk-focus download-models --directory models
   ```

2. Use the example configuration for the local model directory.

   ```bash
   .venv/bin/desk-focus benchmark --config configuration.example.json --iterations 10
   ```

## Next action

Keep the MediaPipe implementation as an accuracy prototype. Compare it with a small ONNX or native LiteRT runtime before packaging.
