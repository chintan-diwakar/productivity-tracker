# Detector Strategy

## Decision

The application runtime will not depend on the Ultralytics Python package during the first implementation.

Ultralytics is useful for model experiments and ONNX export. ONNX Runtime is a smaller production inference layer than the PyTorch stack.

The current application uses an OpenCV frontal-face detector. This detector proves the capture, policy, smoothing, and logging pipeline.

## Target detector pipeline

The target pipeline combines these independent signals:

1. MediaPipe Face Landmarker detects face presence and face landmarks.
2. A head-pose component estimates pitch and screen direction.
3. An ONNX object detector detects the `cell phone` class.
4. A hand component associates the phone with the primary person.
5. The classifier requires agreement between the phone, hand, and head signals.

The classifier returns `UNCERTAIN` when a required signal is absent.

## Ultralytics use

Ultralytics models contain the COCO `cell phone` class. A nano detection model can provide a useful baseline.

The proposed experiment uses this flow:

```text
Ultralytics nano model
        |
Validation on desk-camera images
        |
ONNX export with fixed input size
        |
ONNX Runtime CPU benchmark
        |
Application detector adapter
```

Do not download a model during normal application startup. Package an approved model or require an explicit installation command.

## License constraint

The Ultralytics repository uses AGPL-3.0 and offers a separate enterprise license.

Before distribution, make sure that the project license and model license permit the planned use. This document is not legal advice.

The project can avoid the Ultralytics Python runtime after export. Model license obligations can still apply to an exported model.

## Performance gate

The detector is acceptable only when it meets all these conditions on the reference Ubuntu computer:

- Total resident memory stays below `150 MB`.
- One inference finishes before the next `1 FPS` sample.
- No unbounded memory increase occurs during an eight-hour run.
- Phone-use precision meets the target from the labeled evaluation set.
- The detector returns `UNCERTAIN` for weak or conflicting evidence.

## Next experiment

1. Collect opt-in desk-camera images for the defined edge cases.
2. Export the smallest suitable model to ONNX.
3. Measure memory, latency, and phone precision at `320x240` and `320x320`.
4. Compare the result with a MediaPipe EfficientDet-Lite object detector.
5. Select the backend from measured results and license compatibility.

