# Changelog

## 0.1.0 - Unreleased

This is the first desktop pre-release for personal testing.

### Added

- Local person, phone, hand, face, and head-pitch inference.
- A 60 FPS diagnostic preview with separate low-rate inference.
- Camera selection, widest-view preview, and neutral-head calibration.
- Start, pause, timed pause, system idle, and camera recovery states.
- Focused active time, classified coverage, and daily category totals.
- Midnight rollover, atomic summaries, retention, recovery, and history deletion.
- A labeled-data evaluation command for phone-use precision.
- An Ubuntu 24.04 AMD64 package workflow.
- An Apple Silicon macOS disk-image workflow with signing and notarization support.

### Known limits

- The MediaPipe process used `301-309 MB` in the reference benchmark.
- Phone-use precision does not have a real-world baseline.
- The interface uses a small window instead of a tray icon.
- The macOS package does not support Intel processors.
