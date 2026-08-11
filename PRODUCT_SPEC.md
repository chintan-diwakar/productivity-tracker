# Desk Focus Tracker: Product Specification

## 1. Purpose

Desk Focus Tracker is a local desktop application that estimates desk-focus time from a webcam.

The application samples video at a low rate. It does not record continuous video or audio.

The application gives private feedback to the person who runs it. It is not an employee-monitoring tool.

The application estimates visible behavior, not actual productivity. Looking down can also mean reading, writing, or using another device.

`POSSIBLE_PHONE_USE` means that the detector sees a phone near at least one hand. It does not prove visual attention.

## 2. Product principles

- Process all camera frames on the local computer.
- Do not save raw frames by default.
- Give the user a clear pause control.
- Prefer an `UNCERTAIN` result to an incorrect result.
- Exclude away time and paused time from productivity percentages.
- Show the reason for each classification.
- Keep all thresholds in one configuration.
- Make log deletion easy and complete.

## 3. Status model

The detector records a detailed status. The statistics layer maps that status to a simple productivity label.

| Status code | Meaning | Default statistics label |
| --- | --- | --- |
| `FOCUSED_SCREEN` | One person faces the configured screen area. | Productive |
| `POSSIBLE_PHONE_USE` | A phone is near at least one detected hand. | Unproductive |
| `LOOKING_DOWN` | The head points down, but phone evidence is weak or absent. | Uncertain |
| `LOOKING_AWAY` | The person looks outside the configured screen area. | Uncertain |
| `AWAY` | No person is present for the configured away period. | Excluded |
| `SYSTEM_IDLE` | The computer reports no user input for the configured idle period. | Excluded |
| `UNCERTAIN` | The image or model confidence is insufficient. | Excluded |
| `PAUSED` | The user paused tracking. | Excluded |
| `CAMERA_ERROR` | The application cannot get a valid camera frame. | Excluded |

The first version must not classify every downward head movement as phone use. This rule prevents many predictable false results.

## 4. Minimum viable product

### 4.1 Onboarding and calibration

- Ask for camera permission during the first run.
- Let the user select a camera when more than one camera exists.
- Show a short camera preview during setup.
- Let the user select the main screen direction.
- Measure a neutral head position during a short calibration.
- Explain local processing and log storage before tracking starts.
- Start in the paused state after an incomplete setup.

### 4.2 Frame capture

- Capture one frame each second by default.
- Make the sample rate configurable from `0.2 FPS` to `2 FPS`.
- Resize each frame to a maximum working size of `320x240`.
- Keep only the newest frame when processing falls behind.
- Release each frame buffer after inference.
- Stop capture when tracking is paused.
- Reduce capture work when the user is away or the system is idle.

### 4.3 Detection pipeline

- Detect whether a person or face is present.
- Estimate head direction relative to the calibrated screen direction.
- Detect a mobile phone with a lightweight object model.
- Detect hands or use pose landmarks when the selected model supports them.
- Require one phone-hand association for possible phone use.
- Use head direction as supporting evidence and a confidence signal.
- Return a confidence value and reason code for each result.
- Return `UNCERTAIN` when the required visual evidence is missing.

MediaPipe Tasks Vision and ONNX Runtime are candidate inference backends. The application must hide backend details behind one detector interface.

### 4.4 Classification stability

- Use a short rolling window to prevent rapid status changes.
- Require several consistent samples before a status change.
- Ignore a single low-confidence result between stable results.
- Apply separate thresholds for entering and leaving an unproductive state.
- Record one event when the stable status changes.
- Do not write one log event for every frame.

Initial thresholds can use three matching samples in a five-sample window. Real evaluation data must determine the final values.

### 4.5 Activity and away detection

- Mark the user as away after a configurable period with no detected person.
- Mark the user as idle after a configurable period with no keyboard or pointer input.
- Make operating-system idle detection optional.
- Resume tracking only after a person or user input returns.
- Use a short return delay to prevent repeated away and active changes.
- Exclude away, idle, paused, error, and uncertain periods from classified active time.

### 4.6 Time tracking and statistics

- Track productive, unproductive, uncertain, away, idle, and paused durations.
- Calculate percentages from classified active time only.
- Show the current stable status and its duration.
- Show daily totals in the tray menu.
- Show the time of the last successful camera sample.
- Start a new daily summary at local midnight by default.
- Keep the previous day when the application crosses midnight.
- Rebuild the current summary from the event log after a restart.

The main percentage uses this formula:

```text
productive_time / (productive_time + unproductive_time)
```

The interface must also show excluded and uncertain time. This information prevents a misleading percentage.

### 4.6.1 Tracking sessions

- Start a session when the user selects `Start / Resume` without an open session.
- Keep the same session during a manual or timed pause.
- End the session when the user selects `End session` or quits the application.
- End the session before a camera preview, calibration, or camera change.
- Give each session a unique identifier.
- Reset all session counters when a new session starts.
- Keep daily counters separate from session counters.
- Show every detailed status duration for the current session.
- Store the start time, end time, model version, configuration version, and final status.
- Store the focus ratio, coverage, status durations, and category durations.
- Keep status transitions in the event log with the session identifier.
- Write one atomic JSON summary for each session.

### 4.7 Tray or menu-bar interface

- Show a small status icon.
- Show today’s productive and unproductive time.
- Provide `Start`, `Pause`, `Pause for 15 minutes`, and `Quit` actions.
- Provide an action to open the data folder.
- Provide an action to delete local history.
- Show camera and model errors without repeated notifications.
- Keep the interface usable when tray support is unavailable.

Tkinter can provide a small fallback window. Rumps can support macOS, and AppIndicator can support compatible Linux desktops.

### 4.8 Local data storage

- Store status transitions in a local JSON Lines file.
- Store one daily summary in a JSON file.
- Use local timestamps with an explicit UTC offset.
- Include the model version and configuration version in each event.
- Write summary updates with an atomic file replacement.
- Recover valid records from a partially written event file.
- Use a configurable retention period.
- Do not include raw frames, face images, or biometric templates in logs.

Recommended file layout:

```text
data/
  events-2026-08-10.jsonl
  summary-2026-08-10.json
  sessions/
    7cb3d89a.../
      summary.json
      diagnostics/
        manifest.jsonl
        000001-POSSIBLE_PHONE_USE.jpg
```

Example event:

```json
{
  "timestamp": "2026-08-10T14:30:05+05:30",
  "status": "POSSIBLE_PHONE_USE",
  "confidence": 0.87,
  "reason": "phone_near_hand_and_downward_head_pose",
  "model_version": "phone-detector-1",
  "configuration_version": 2
}
```

### 4.9 Privacy and control

- Keep camera processing offline by default.
- Show a visible tracking state at all times.
- Do not try to disable or hide the camera activity light.
- Give the user a pause keyboard shortcut.
- Give the user a complete local data deletion action.
- Store logs with permissions that restrict access to the current user.
- Require explicit consent before diagnostic frame storage.
- Keep diagnostic frame storage disabled by default.

### 4.9.1 Diagnostic output

- Provide a `Save diagnostic output` toggle in the interface.
- Explain that diagnostic images can show the user and the room.
- Apply a toggle change to the next session.
- Save only sampled inference frames when the toggle is enabled.
- Do not save continuous preview video.
- Save each frame at the inference resolution.
- Add the status, confidence, and reason to each saved image.
- Write a JSON Lines manifest with the evidence for each image.
- Store diagnostic output inside its session folder.
- Limit diagnostic storage to `3600` frames for each session.
- Delete diagnostic output when the user deletes local history.

## 5. Later features

- Weekly and monthly trend views.
- A configurable work schedule.
- Break reminders after long focus periods.
- Manual corrections for recent status periods.
- User-defined labels and status rules.
- Multiple screen-direction profiles.
- Automatic camera selection for docked and undocked use.
- Optional encrypted local logs.
- Export to CSV and JSON.
- An optional local-only model improvement workflow.
- Battery-aware sampling on laptops.
- Accessibility options for colors, icons, and notifications.

Cloud synchronization, remote dashboards, identity recognition, and manager reports are outside the initial scope.

## 6. Proposed architecture

```text
Capture scheduler
      |
Activity gate ---- Operating-system idle signal
      |
Frame preprocessor
      |
Person, head, hand, and phone detectors
      |
Temporal classifier
      |
Status event service
     / \
Local logs   Tray interface
```

### 6.1 Main components

`CaptureService` owns the webcam and produces the newest resized frame.

`ActivityService` detects system idle time and controls low-power behavior.

`DetectionService` runs the selected MediaPipe or ONNX backend.

`ClassificationService` combines signals and applies confidence thresholds.

`StateService` applies the rolling window and creates stable status transitions.

`LogService` writes events, updates summaries, and applies the retention policy.

`TrayService` shows current statistics and accepts user actions.

### 6.2 Processing rules

- Use a bounded queue with a capacity of one frame.
- Drop a stale frame instead of delaying the next result.
- Run camera capture and inference outside the interface thread.
- Keep one loaded model instance for the application lifetime.
- Clear temporary arrays after each inference pass.
- Use monotonic time for duration measurements.
- Use wall-clock time only for timestamps and daily boundaries.
- Reduce the sample rate after repeated `AWAY` results.
- Restore the normal sample rate after presence or user input returns.

## 7. Configuration

The first version can expose these values in `configuration.json`:

| Key | Initial value | Purpose |
| --- | --- | --- |
| `camera_index` | `0` | Selected camera |
| `capture_fps` | `1.0` | Active sample rate |
| `away_capture_fps` | `0.2` | Reduced away sample rate |
| `frame_width` | `320` | Working frame width |
| `frame_height` | `240` | Working frame height |
| `idle_timeout_seconds` | `300` | System idle threshold |
| `away_timeout_seconds` | `5` | Continuous no-person threshold |
| `window_samples` | `5` | Temporal classification window |
| `minimum_matching_samples` | `3` | Stable result threshold |
| `daily_reset_time` | `00:00` | Local daily boundary |
| `retention_days` | `30` | Local log retention |
| `save_diagnostic_frames` | `false` | Diagnostic image storage |
| `diagnostic_frame_limit` | `3600` | Maximum diagnostic images in one session |
| `object_score_threshold` | `0.15` | Phone detection threshold |
| `person_score_threshold` | `0.35` | Person detection threshold |

Model confidence thresholds belong in the same configuration. Calibration and evaluation must determine their initial values.

## 8. Edge cases

### 8.1 Camera and image input

| Edge case | Required behavior |
| --- | --- |
| Camera permission is denied. | Show `CAMERA_ERROR` and instructions for system permission. Do not retry continuously. |
| Another application owns the camera. | Retry with a delay and keep the interface responsive. |
| The camera disconnects. | Release the old handle and offer camera selection. |
| The camera returns a black or frozen frame. | Mark the sample invalid after repeated identical or dark frames. |
| The lens is covered. | Return `UNCERTAIN`. Do not record unproductive time. |
| The room is dark or strongly backlit. | Return `UNCERTAIN` when confidence falls below the threshold. |
| The frame is mirrored. | Apply one consistent orientation before calibration and inference. |
| The camera changes after docking. | Show an error and offer the available cameras. |
| Inference takes longer than one second. | Drop stale frames and process the newest frame. |

### 8.2 People and desk behavior

| Edge case | Required behavior |
| --- | --- |
| No person is visible. | Enter `AWAY` after the configured delay. |
| Multiple people are visible. | Return `UNCERTAIN` unless one calibrated primary face is clear. |
| A person enters the background. | Do not replace the primary person from one frame. |
| The user turns to a second monitor. | Use a calibrated screen profile or return `LOOKING_AWAY`. |
| The user uses a standing desk. | Allow a second calibration profile. |
| The user leans, reclines, or changes chair height. | Use relative head angles and tolerant thresholds. |
| The user wears glasses, a mask, or a hat. | Reduce confidence when landmarks are unreliable. |
| The user rests a hand near the face. | Require phone evidence before `POSSIBLE_PHONE_USE`. |
| The user drinks or eats. | Require phone evidence before `POSSIBLE_PHONE_USE`. |
| The user reads a book or writes notes. | Record `LOOKING_DOWN`, not phone use. |
| The user uses a tablet or e-reader. | Return an explicit device result only when the model supports it. |
| A phone sits in a stand near the monitor. | Require the phone to be near at least one detected hand. |
| The user holds a phone during a video call. | Record possible phone use. Do not infer attention or intent. |
| The user looks at the keyboard. | Ignore short downward movements through temporal smoothing. |
| The user closes their eyes or stretches. | Ignore short events and return `UNCERTAIN` for weak landmarks. |
| The user has nonstandard movement or posture. | Support calibration and manual policy changes. |

### 8.3 Model errors and fairness

| Edge case | Required behavior |
| --- | --- |
| The phone is partly hidden. | Use the combined confidence and return `UNCERTAIN` when evidence is weak. |
| A remote control resembles a phone. | Require a phone detection near at least one hand. Keep the result as possible phone use. |
| A phone appears on another screen. | Use object location and person association to reject it. |
| Detection changes every frame. | Keep the stable status until the temporal threshold is met. |
| The model file is absent or corrupt. | Stop inference and show a model error. |
| The model backend crashes. | Capture the error, release resources, and permit a restart. |
| Accuracy differs across skin tones or lighting. | Measure results across representative users and environments. |
| Confidence remains low after calibration. | Explain the camera or lighting problem. Do not force a label. |

The project must publish evaluation methods before it describes the detector as accurate.

### 8.4 Activity and statistics

| Edge case | Required behavior |
| --- | --- |
| A video plays while the user is away. | Use person presence and system input together. |
| The user watches content without input. | Do not mark idle time as unproductive. Show it as excluded. |
| The user reads without keyboard input. | Keep visual presence separate from system idle state. |
| A status lasts less than the smoothing window. | Do not create a stable event. |
| The application starts during an active session. | Start with `UNCERTAIN` until the window fills. |
| The application restarts. | Rebuild today’s counters from valid events. |
| Two application instances start. | Use a process lock and keep one writer. |
| The application crosses midnight. | Close the old summary and start the new local day. |
| The time zone changes. | Close the current day and record the new UTC offset. |
| Daylight-saving time changes. | Use monotonic durations and offset-aware timestamps. |
| The system clock moves backward. | Keep durations monotonic and record the wall-clock change. |
| The computer sleeps. | Exclude the sleep interval and resume with `UNCERTAIN`. |
| The user pauses near midnight. | Split the paused duration across the daily boundary. |
| The user pauses a session. | Keep the session identifier and include the paused duration. |
| The user starts after an ended session. | Create a session identifier and reset all session counters. |
| The application stops during a session. | Keep completed transitions and mark the session as interrupted after recovery. |

### 8.5 Storage and recovery

| Edge case | Required behavior |
| --- | --- |
| The application stops during a write. | Ignore an incomplete final JSON Lines record. |
| A summary file is corrupt. | Rebuild it from valid event records. |
| The disk is full. | Stop log writes and show one persistent error. |
| The data folder is unavailable. | Keep a bounded in-memory event list and show an error. |
| An old configuration is loaded. | Migrate supported fields or use documented defaults. |
| The user deletes history during tracking. | Close active files, delete history, and start new files. |
| The retention job finds an unknown file. | Leave the unknown file unchanged. |
| A log contains an unknown status code. | Preserve the record and exclude it from statistics. |
| Diagnostic storage reaches its frame limit. | Stop image writes and keep status logging active. |
| A diagnostic image write fails. | Disable diagnostic output for the session and keep tracking active. |

### 8.6 Interface and platform behavior

| Edge case | Required behavior |
| --- | --- |
| The desktop has no system tray. | Open the fallback status window. |
| The tray process restarts. | Reconnect it to the running tracking service. |
| The user quits during inference. | Stop new capture, finish or cancel inference, and release the camera. |
| Notifications are disabled. | Keep errors visible in the tray menu. |
| The system starts the application automatically. | Respect the last pause policy and permission state. |
| The user selects pause for 15 minutes. | Use monotonic time and show the remaining pause time. |

## 9. Performance and reliability targets

- Keep resident memory below `150 MB` after a 30-minute session.
- Show no continuous memory increase during an eight-hour test.
- Process a normal sample before the next scheduled sample.
- Keep the capture queue at one frame or less.
- Keep the interface responsive during camera and model failures.
- Release the camera within two seconds after pause or quit.
- Store no raw frames during normal operation.
- Recover daily totals after an unplanned restart.
- Keep event logs below `1 MB` per normal workday by logging transitions.
- Keep diagnostic output disabled during normal operation.

CPU use depends on the model and computer. Each supported platform needs a measured CPU budget before release.

## 10. Evaluation plan

- Build an opt-in, labeled test set without retaining participant identity.
- Include different lighting, cameras, skin tones, glasses, postures, and screen layouts.
- Label phone use, note-taking, reading, keyboard glances, away time, and normal screen focus.
- Measure precision, recall, false-positive rate, and uncertain rate for each status.
- Measure status accuracy after temporal smoothing.
- Measure memory and CPU use during an eight-hour run.
- Measure camera recovery after disconnect, sleep, and permission changes.
- Keep the test data separate from normal user logs.

Phone-use precision is more important than recall for the first version. A missed phone event is less harmful than an incorrect accusation.

## 11. MVP acceptance criteria

The MVP is complete when all these conditions are true:

- The application runs on one selected desktop platform.
- The user can complete camera setup and calibration.
- The application samples at `1 FPS` and processes `320x240` frames.
- The detector emits every status in the defined status model.
- Temporal smoothing prevents a one-frame status change.
- The interface shows current status and daily totals.
- The interface shows all KPI values for the current session.
- A new session starts with zero session counters.
- Each completed session has one local JSON summary.
- The diagnostic toggle saves sampled output in the current session folder.
- Pause, timed pause, resume, and quit work without a restart.
- Event and summary files recover after an unplanned stop.
- Daily rollover works across sleep and restart.
- Normal operation stores no raw camera frames.
- Resident memory stays below `150 MB` in the defined test environment.
- The project reports measured model results on a labeled test set.

## 12. Open decisions

1. Select the first supported platform: macOS or Ubuntu.
2. Select MediaPipe Tasks Vision or ONNX Runtime for the first detector backend.
3. Select an existing phone detector or collect data for a custom model.
4. Define the policy for sustained `LOOKING_DOWN` time.
5. Define the default retention period and data directory.
6. Select the operating-system API for idle detection.
7. Decide whether the first interface uses Tkinter or a native tray library.
8. Define the first accuracy target after a baseline evaluation.

## 13. Suggested implementation stages

1. Build camera capture, resizing, and resource cleanup.
2. Add person presence and head-direction estimation.
3. Add phone detection and combined classification rules.
4. Add temporal smoothing and activity detection.
5. Add event logs, summaries, recovery, and daily rollover.
6. Add the tray interface, pause controls, and error states.
7. Run performance, recovery, and accuracy evaluations.
8. Package the application for the selected platform.
