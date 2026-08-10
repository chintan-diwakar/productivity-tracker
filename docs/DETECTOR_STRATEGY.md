# Detector Strategy

## Decision

The first prototype uses MediaPipe Tasks for object, face, and hand detection.

EfficientDet-Lite0 INT8 detects the COCO `person` and `cell phone` classes. Face Landmarker supplies a facial transformation matrix.

Hand Landmarker supplies normalized hand points. The application compares those points with the center of each phone box.

## Target detector pipeline

The target pipeline combines these independent signals:

1. EfficientDet-Lite0 detects people and phones.
2. Face Landmarker detects faces and estimates head pitch.
3. Hand Landmarker locates hands when a phone is visible.
4. A distance rule associates the phone with a hand.
5. The classifier requires agreement between the phone, hand, and head signals.

The classifier returns `UNCERTAIN` when a required signal is absent.

## Classification rules

The classifier applies these rules in order:

1. No person and no face becomes `AWAY` after the away delay.
2. Multiple people or faces become `UNCERTAIN`.
3. A person without a visible face becomes `LOOKING_AWAY`.
4. Missing head pose becomes `UNCERTAIN`.
5. A nearby phone, hand, and downward head become `POSSIBLE_PHONE_USE`.
6. A downward head without complete phone evidence becomes `LOOKING_DOWN`.
7. A phone near a hand without a downward head becomes `UNCERTAIN`.
8. Other single-face results become `FOCUSED_SCREEN`.

## Ultralytics fallback

Ultralytics remains the fallback when EfficientDet-Lite0 misses too many phones. A nano YOLO model can provide a second baseline.

The proposed experiment uses this flow:

```text
Ultralytics nano model
        |
Evaluation on desk-camera images
        |
ONNX export with fixed input size
        |
ONNX Runtime CPU benchmark
        |
Application detector adapter
```

The Ultralytics package stays outside the application runtime. The application will use ONNX Runtime for an exported model.

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

## Evaluation sequence

1. Measure the MediaPipe prototype on the reference Ubuntu computer.
2. Collect opt-in desk-camera images for the defined edge cases.
3. Measure phone precision and recall for EfficientDet-Lite0.
4. If phone recall is insufficient, export a nano YOLO model to ONNX.
5. Compare memory, latency, accuracy, and license compatibility.
