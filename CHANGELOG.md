# Changelog

## 1.0.0 - 2026-08-12

This is the first release. The product name is Know Your Focus (KYF). The name before the first release was Desk Focus Tracker.

### Added

- Local person, phone, hand, face, and head-pitch inference.
- A GTK 4 and Libadwaita interface for Ubuntu, with the Rust `gtk4-rs` bindings.
- A local JSON Lines protocol between the interface and the Python tracking engine.
- A 60 FPS diagnostic preview with separate low-rate inference.
- Camera selection by device name, widest-view preview, and neutral-head calibration.
- Start, pause, timed pause, system idle, and camera recovery states.
- Focused active time, classified coverage, and daily category totals.
- An away status after 5 seconds of continuous no-person evidence.
- Midnight rollover, atomic summaries, retention, recovery, and history deletion.
- Recovery of interrupted session summaries at startup.
- Session diagnostics with an optional annotated frame output.
- A labeled-data evaluation command for phone-use precision.
- An Ubuntu 24.04 AMD64 package workflow.
- An Apple Silicon macOS disk-image workflow with signing and notarization support.

### Known limits

- The package uses about `400 MB` after installation.
- The MediaPipe process used `301-309 MB` in the reference benchmark.
- Phone-use precision does not have a real-world baseline.
- The application does not have a tray icon or a menu-bar icon.
- The macOS package does not support Intel processors.
