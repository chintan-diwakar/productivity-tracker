use adw::prelude::*;
use gtk::glib;
use serde::Deserialize;
use serde_json::{Value, json};
use std::cell::{Cell, RefCell};
use std::collections::HashMap;
use std::env;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::rc::Rc;
use std::sync::mpsc::{self, Receiver, Sender, TryRecvError};
use std::thread;
use std::time::Duration;

const APP_ID: &str = "dev.chintandiwakar.KnowYourFocus";

#[derive(Clone, Debug)]
enum RequestKind {
    Snapshot,
    Config,
    Cameras,
    ModelsReady,
    Sessions,
    Action(Action),
    Shutdown,
}

#[derive(Clone, Debug)]
enum Action {
    Start,
    Pause,
    PauseFor,
    EndSession,
    SaveCamera,
    DownloadModels,
    Preview,
    Calibrate,
    SaveDiagnostics(bool),
    OpenData,
    OpenSession,
    DeleteHistory,
}

impl Action {
    fn completion_message(&self, result: &Value) -> String {
        match self {
            Self::Start => "Tracking started.".into(),
            Self::Pause => "Tracking paused.".into(),
            Self::PauseFor => "Tracking paused for 15 minutes.".into(),
            Self::EndSession => "Session ended.".into(),
            Self::SaveCamera => "Camera setting saved.".into(),
            Self::DownloadModels => "Models are ready.".into(),
            Self::Preview => "Preview closed. Start tracking when you are ready.".into(),
            Self::Calibrate => {
                let pitch = result
                    .get("neutral_pitch_degrees")
                    .and_then(Value::as_f64)
                    .unwrap_or_default();
                format!("Calibration complete. Neutral head angle: {pitch:.1}°.")
            }
            Self::SaveDiagnostics(enabled) => {
                let state = if *enabled { "enabled" } else { "disabled" };
                format!("Diagnostic output is {state} for the next session.")
            }
            Self::OpenData | Self::OpenSession => "Opened the local data folder.".into(),
            Self::DeleteHistory => "Local history deleted.".into(),
        }
    }
}

#[derive(Debug)]
struct EngineRequest {
    kind: RequestKind,
    command: &'static str,
    arguments: Value,
}

#[derive(Debug)]
struct EngineResponse {
    kind: RequestKind,
    result: Result<Value, String>,
}

#[derive(Deserialize)]
struct ProtocolResponse {
    ok: bool,
    #[serde(default)]
    result: Value,
    error: Option<String>,
}

struct EngineProcess {
    child: Child,
    input: ChildStdin,
    output: BufReader<ChildStdout>,
    next_id: u64,
}

impl EngineProcess {
    fn start(config_path: Option<&Path>) -> Result<Self, String> {
        let mut command = engine_command()?;
        if let Some(path) = config_path {
            command.arg("--config").arg(path);
        }
        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|error| format!("Cannot start the tracking engine: {error}"))?;
        let input = child
            .stdin
            .take()
            .ok_or("The tracking engine has no input")?;
        let output = child
            .stdout
            .take()
            .ok_or("The tracking engine has no output")?;
        Ok(Self {
            child,
            input,
            output: BufReader::new(output),
            next_id: 1,
        })
    }

    fn request(&mut self, command: &str, arguments: Value) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;
        let message = json!({"id": id, "command": command, "arguments": arguments});
        serde_json::to_writer(&mut self.input, &message)
            .map_err(|error| format!("Cannot encode an engine request: {error}"))?;
        self.input
            .write_all(b"\n")
            .and_then(|()| self.input.flush())
            .map_err(|error| format!("Cannot send a request to the tracking engine: {error}"))?;

        let mut line = String::new();
        let count = self
            .output
            .read_line(&mut line)
            .map_err(|error| format!("Cannot read the tracking engine response: {error}"))?;
        if count == 0 {
            return Err("The tracking engine stopped unexpectedly.".into());
        }
        let response: ProtocolResponse = serde_json::from_str(&line)
            .map_err(|error| format!("The tracking engine returned invalid data: {error}"))?;
        if response.ok {
            Ok(response.result)
        } else {
            Err(response
                .error
                .unwrap_or_else(|| "The tracking engine reported an error.".into()))
        }
    }
}

impl Drop for EngineProcess {
    fn drop(&mut self) {
        let _ = self.child.try_wait();
    }
}

fn engine_command() -> Result<Command, String> {
    if let Some(executable) = env::var_os("KYF_ENGINE") {
        return Ok(Command::new(executable));
    }

    let current_executable = env::current_exe()
        .map_err(|error| format!("Cannot locate the application executable: {error}"))?;
    let executable_directory = current_executable
        .parent()
        .ok_or("Cannot locate the application directory")?;
    let mut candidates = vec![executable_directory.join("engine").join("kyf-engine")];
    if let Some(contents) = executable_directory.parent() {
        candidates.push(contents.join("Resources").join("engine").join("kyf-engine"));
    }
    candidates.push(PathBuf::from(".venv/bin/kyf-engine"));
    for candidate in candidates {
        if candidate.is_file() {
            return Ok(Command::new(candidate));
        }
    }

    Ok(Command::new("kyf-engine"))
}

fn start_engine_worker(
    config_path: Option<PathBuf>,
) -> (Sender<EngineRequest>, Receiver<EngineResponse>) {
    let (request_sender, request_receiver) = mpsc::channel::<EngineRequest>();
    let (response_sender, response_receiver) = mpsc::channel::<EngineResponse>();
    thread::spawn(move || {
        let mut engine = match EngineProcess::start(config_path.as_deref()) {
            Ok(engine) => engine,
            Err(error) => {
                let _ = response_sender.send(EngineResponse {
                    kind: RequestKind::Config,
                    result: Err(error),
                });
                return;
            }
        };
        for request in request_receiver {
            let should_stop = matches!(request.kind, RequestKind::Shutdown);
            let result = engine.request(request.command, request.arguments);
            if response_sender
                .send(EngineResponse {
                    kind: request.kind,
                    result,
                })
                .is_err()
            {
                break;
            }
            if should_stop {
                break;
            }
        }
    });
    (request_sender, response_receiver)
}

#[derive(Default, Deserialize)]
struct Metrics {
    #[serde(default)]
    status_seconds: HashMap<String, f64>,
    classified_coverage: Option<f64>,
}

#[derive(Default, Deserialize)]
struct SessionMetrics {
    session_id: String,
    started_at: String,
    state: String,
    diagnostic_output_enabled: bool,
    diagnostic_frame_count: u64,
    #[serde(default)]
    status_seconds: HashMap<String, f64>,
    focused_active_ratio: Option<f64>,
    classified_coverage: Option<f64>,
}

#[derive(Deserialize)]
struct Snapshot {
    status: String,
    status_seconds: f64,
    metrics: Metrics,
    session_metrics: Option<SessionMetrics>,
    last_sample: Option<String>,
    error: Option<String>,
}

#[derive(Clone)]
struct Ui {
    window: adw::ApplicationWindow,
    toast_overlay: adw::ToastOverlay,
    status_card: gtk::Box,
    status_label: gtk::Label,
    status_duration: gtk::Label,
    session_summary: gtk::Label,
    metric_values: HashMap<&'static str, gtk::Label>,
    today_label: gtk::Label,
    last_sample_label: gtk::Label,
    message_label: gtk::Label,
    camera_dropdown: gtk::DropDown,
    camera_indices: Rc<RefCell<Vec<i64>>>,
    diagnostic_row: adw::SwitchRow,
    start_button: gtk::Button,
    pause_button: gtk::Button,
    pause_for_button: gtk::Button,
    end_button: gtk::Button,
    save_camera_button: gtk::Button,
    refresh_cameras_button: gtk::Button,
    models_button: gtk::Button,
    preview_button: gtk::Button,
    calibrate_button: gtk::Button,
    open_session_row: adw::ActionRow,
    open_data_row: adw::ActionRow,
    delete_row: adw::ActionRow,
    history_button: gtk::Button,
    action_widgets: Vec<gtk::Widget>,
}

impl Ui {
    fn set_busy(&self, busy: bool) {
        for widget in &self.action_widgets {
            widget.set_sensitive(!busy);
        }
        if !busy && self.camera_indices.borrow().is_empty() {
            self.camera_dropdown.set_sensitive(false);
            self.save_camera_button.set_sensitive(false);
        }
    }

    fn toast(&self, message: &str) {
        self.toast_overlay.add_toast(adw::Toast::new(message));
    }

    fn set_status_appearance(&self, status: &str) {
        for class_name in ["success", "warning", "error", "accent"] {
            self.status_card.remove_css_class(class_name);
        }
        let class_name = match status {
            "FOCUSED_SCREEN" => "success",
            "POSSIBLE_PHONE_USE" | "LOOKING_DOWN" | "LOOKING_AWAY" => "warning",
            "CAMERA_ERROR" => "error",
            _ => "accent",
        };
        self.status_card.add_css_class(class_name);
    }

    fn apply_snapshot(&self, snapshot: Snapshot) {
        self.status_label.set_label(status_label(&snapshot.status));
        self.status_duration
            .set_label(&format_duration(snapshot.status_seconds));
        self.set_status_appearance(&snapshot.status);

        let empty_statuses = HashMap::new();
        let (statuses, focus_ratio, coverage) = match snapshot.session_metrics.as_ref() {
            Some(session) => {
                let state = if session.state == "active" {
                    "Active"
                } else {
                    "Ended"
                };
                let diagnostics = if session.diagnostic_output_enabled {
                    format!(" · {} diagnostic images", session.diagnostic_frame_count)
                } else {
                    String::new()
                };
                self.session_summary.set_label(&format!(
                    "Session {} · {state} · Started {}{diagnostics}",
                    session.session_id.chars().take(8).collect::<String>(),
                    display_time(&session.started_at)
                ));
                (
                    &session.status_seconds,
                    session.focused_active_ratio,
                    session.classified_coverage,
                )
            }
            None => {
                self.session_summary
                    .set_label("No session. Select Start to create one.");
                (&empty_statuses, None, None)
            }
        };
        self.set_metric("focus_ratio", &format_ratio(focus_ratio));
        self.set_metric("coverage", &format_ratio(coverage));
        for (key, status) in [
            ("focused", "FOCUSED_SCREEN"),
            ("phone", "POSSIBLE_PHONE_USE"),
            ("looking_down", "LOOKING_DOWN"),
            ("looking_away", "LOOKING_AWAY"),
            ("away", "AWAY"),
            ("uncertain", "UNCERTAIN"),
            ("idle", "SYSTEM_IDLE"),
            ("paused", "PAUSED"),
            ("camera_error", "CAMERA_ERROR"),
        ] {
            self.set_metric(key, &format_duration(*statuses.get(status).unwrap_or(&0.0)));
        }

        let daily_focused = snapshot
            .metrics
            .status_seconds
            .get("FOCUSED_SCREEN")
            .copied()
            .unwrap_or_default();
        let daily_phone = snapshot
            .metrics
            .status_seconds
            .get("POSSIBLE_PHONE_USE")
            .copied()
            .unwrap_or_default();
        self.today_label.set_label(&format!(
            "Today · Focused {} · Phone {} · Coverage {}",
            format_duration(daily_focused),
            format_duration(daily_phone),
            format_ratio(snapshot.metrics.classified_coverage)
        ));
        self.last_sample_label.set_label(
            snapshot
                .last_sample
                .as_deref()
                .map(|value| format!("Last camera sample: {}", display_time(value)))
                .as_deref()
                .unwrap_or("No successful camera sample"),
        );
        if let Some(error) = snapshot.error {
            self.message_label.set_label(&error);
        }
    }

    fn set_metric(&self, name: &str, value: &str) {
        if let Some(label) = self.metric_values.get(name) {
            label.set_label(value);
        }
    }

    fn apply_camera_list(&self, value: Value, configured_index: i64) -> Result<(), String> {
        let cameras = value
            .as_array()
            .ok_or("The tracking engine returned an invalid camera list.")?;
        let mut labels = Vec::new();
        let mut indices = Vec::new();
        for camera in cameras {
            let index = camera
                .get("index")
                .and_then(Value::as_i64)
                .ok_or("A detected camera has no valid index.")?;
            let name = camera
                .get("name")
                .and_then(Value::as_str)
                .unwrap_or("Camera");
            labels.push(format!("{name} · Camera {index}"));
            indices.push(index);
        }

        if !indices.contains(&configured_index) && !indices.is_empty() {
            labels.push(format!(
                "Camera {configured_index} · saved, currently unavailable"
            ));
            indices.push(configured_index);
        }

        if indices.is_empty() {
            let model = gtk::StringList::new(&["No cameras detected"]);
            self.camera_dropdown.set_model(Some(&model));
            self.camera_dropdown.set_sensitive(false);
            self.save_camera_button.set_sensitive(false);
            self.camera_indices.replace(indices);
            return Ok(());
        }

        let selected = indices
            .iter()
            .position(|index| *index == configured_index)
            .unwrap_or(0) as u32;
        let label_refs: Vec<&str> = labels.iter().map(String::as_str).collect();
        let model = gtk::StringList::new(&label_refs);
        self.camera_dropdown.set_model(Some(&model));
        self.camera_dropdown.set_selected(selected);
        self.camera_dropdown.set_sensitive(true);
        self.save_camera_button.set_sensitive(true);
        self.camera_indices.replace(indices);
        Ok(())
    }
}

struct AppState {
    sender: Sender<EngineRequest>,
    snapshot_pending: Cell<bool>,
    busy: Cell<bool>,
    changing_diagnostic_switch: Cell<bool>,
    configured_camera_index: Cell<i64>,
}

impl AppState {
    fn send(&self, request: EngineRequest) -> bool {
        self.sender.send(request).is_ok()
    }
}

fn build_ui(application: &adw::Application, config_path: Option<PathBuf>) {
    load_styles();
    let (sender, receiver) = start_engine_worker(config_path);
    let ui = Rc::new(create_ui(application));
    let state = Rc::new(AppState {
        sender,
        snapshot_pending: Cell::new(false),
        busy: Cell::new(false),
        changing_diagnostic_switch: Cell::new(false),
        configured_camera_index: Cell::new(0),
    });
    connect_actions(&ui, &state);

    state.send(EngineRequest {
        kind: RequestKind::Config,
        command: "config",
        arguments: json!({}),
    });
    state.send(EngineRequest {
        kind: RequestKind::Cameras,
        command: "list_cameras",
        arguments: json!({}),
    });
    state.send(EngineRequest {
        kind: RequestKind::ModelsReady,
        command: "models_ready",
        arguments: json!({}),
    });
    request_snapshot(&state);

    let response_ui = Rc::clone(&ui);
    let response_state = Rc::clone(&state);
    glib::timeout_add_local(Duration::from_millis(100), move || {
        loop {
            match receiver.try_recv() {
                Ok(response) => handle_response(&response_ui, &response_state, response),
                Err(TryRecvError::Empty) => break,
                Err(TryRecvError::Disconnected) => {
                    response_ui.message_label.set_label(
                        "The tracking engine stopped. Close and reopen the application.",
                    );
                    response_ui.set_busy(true);
                    return glib::ControlFlow::Break;
                }
            }
        }
        glib::ControlFlow::Continue
    });

    let poll_state = Rc::clone(&state);
    glib::timeout_add_local(Duration::from_secs(1), move || {
        if !poll_state.busy.get() {
            request_snapshot(&poll_state);
        }
        glib::ControlFlow::Continue
    });

    let close_state = Rc::clone(&state);
    ui.window.connect_close_request(move |_| {
        let _ = close_state.send(EngineRequest {
            kind: RequestKind::Shutdown,
            command: "shutdown",
            arguments: json!({}),
        });
        glib::Propagation::Proceed
    });
    ui.window.present();
}

fn create_ui(application: &adw::Application) -> Ui {
    let window = adw::ApplicationWindow::builder()
        .application(application)
        .title("Know Your Focus")
        .default_width(660)
        .default_height(820)
        .build();

    let header = adw::HeaderBar::new();
    let history_button = gtk::Button::builder()
        .icon_name("document-open-recent-symbolic")
        .tooltip_text("Session history")
        .build();
    header.pack_end(&history_button);

    let content = gtk::Box::new(gtk::Orientation::Vertical, 18);
    content.set_margin_top(24);
    content.set_margin_bottom(24);
    content.set_margin_start(18);
    content.set_margin_end(18);

    let status_card = gtk::Box::new(gtk::Orientation::Vertical, 4);
    status_card.add_css_class("card");
    status_card.add_css_class("status-card");
    status_card.add_css_class("accent");
    let status_caption = gtk::Label::builder()
        .label("CURRENT STATUS")
        .halign(gtk::Align::Start)
        .build();
    status_caption.add_css_class("caption");
    let status_label = gtk::Label::builder()
        .label("Paused")
        .halign(gtk::Align::Start)
        .wrap(true)
        .build();
    status_label.add_css_class("status-title");
    let status_duration = gtk::Label::builder()
        .label("0s")
        .halign(gtk::Align::Start)
        .build();
    status_duration.add_css_class("status-duration");
    status_card.append(&status_caption);
    status_card.append(&status_label);
    status_card.append(&status_duration);
    content.append(&status_card);

    let session_summary = gtk::Label::builder()
        .label("No session. Select Start to create one.")
        .halign(gtk::Align::Start)
        .wrap(true)
        .build();
    session_summary.add_css_class("session-summary");
    content.append(&session_summary);

    let metrics_group = adw::PreferencesGroup::builder()
        .title("Current session")
        .description("Time resets when you end the session")
        .build();
    let mut metric_values = HashMap::new();
    for (key, title, initial) in [
        ("focus_ratio", "Focus ratio", "Not enough data"),
        ("coverage", "Classified coverage", "Not enough data"),
        ("focused", "Focused", "0s"),
        ("phone", "Possible phone use", "0s"),
        ("looking_down", "Looking down", "0s"),
        ("looking_away", "Looking away", "0s"),
        ("away", "Away · no person", "0s"),
        ("uncertain", "Uncertain", "0s"),
        ("idle", "System idle", "0s"),
        ("paused", "Paused", "0s"),
        ("camera_error", "Camera error", "0s"),
    ] {
        let value = gtk::Label::new(Some(initial));
        value.add_css_class("metric-value");
        let row = adw::ActionRow::builder().title(title).build();
        row.add_suffix(&value);
        metrics_group.add(&row);
        metric_values.insert(key, value);
    }
    content.append(&metrics_group);

    let controls = gtk::Grid::builder()
        .column_spacing(8)
        .row_spacing(8)
        .column_homogeneous(true)
        .build();
    let start_button = gtk::Button::with_label("Start / Resume");
    start_button.add_css_class("suggested-action");
    let pause_button = gtk::Button::with_label("Pause");
    let pause_for_button = gtk::Button::with_label("Pause 15 min");
    let end_button = gtk::Button::with_label("End session");
    controls.attach(&start_button, 0, 0, 1, 1);
    controls.attach(&pause_button, 1, 0, 1, 1);
    controls.attach(&pause_for_button, 0, 1, 1, 1);
    controls.attach(&end_button, 1, 1, 1, 1);
    content.append(&controls);

    let camera_group = adw::PreferencesGroup::builder()
        .title("Camera setup")
        .build();
    let initial_camera_model = gtk::StringList::new(&["Detecting cameras…"]);
    let camera_dropdown = gtk::DropDown::builder()
        .model(&initial_camera_model)
        .sensitive(false)
        .hexpand(true)
        .build();
    let camera_indices = Rc::new(RefCell::new(Vec::new()));
    let camera_row = adw::ActionRow::builder()
        .title("Camera")
        .subtitle("Select an available webcam")
        .build();
    camera_row.add_suffix(&camera_dropdown);
    let refresh_cameras_button = gtk::Button::builder()
        .icon_name("view-refresh-symbolic")
        .tooltip_text("Refresh available cameras")
        .valign(gtk::Align::Center)
        .build();
    camera_row.add_suffix(&refresh_cameras_button);
    let save_camera_button = gtk::Button::with_label("Save");
    save_camera_button.set_valign(gtk::Align::Center);
    camera_row.add_suffix(&save_camera_button);
    camera_group.add(&camera_row);

    let camera_buttons = gtk::Box::new(gtk::Orientation::Horizontal, 8);
    camera_buttons.set_homogeneous(true);
    let models_button = gtk::Button::with_label("Download models");
    let preview_button = gtk::Button::with_label("Camera preview");
    let calibrate_button = gtk::Button::with_label("Calibrate");
    camera_buttons.append(&models_button);
    camera_buttons.append(&preview_button);
    camera_buttons.append(&calibrate_button);
    camera_group.add(&camera_buttons);
    content.append(&camera_group);

    let privacy_group = adw::PreferencesGroup::builder().title("Privacy").build();
    let diagnostic_row = adw::SwitchRow::builder()
        .title("Save diagnostic output")
        .subtitle("Save sampled annotated images for the next session")
        .build();
    privacy_group.add(&diagnostic_row);
    let open_session_row = adw::ActionRow::builder()
        .title("Session files")
        .subtitle("Open local summaries and optional diagnostic images")
        .activatable(true)
        .build();
    open_session_row.add_suffix(&gtk::Image::from_icon_name("folder-open-symbolic"));
    privacy_group.add(&open_session_row);
    let open_data_row = adw::ActionRow::builder()
        .title("All local data")
        .activatable(true)
        .build();
    open_data_row.add_suffix(&gtk::Image::from_icon_name("folder-open-symbolic"));
    privacy_group.add(&open_data_row);
    let delete_row = adw::ActionRow::builder()
        .title("Delete history")
        .subtitle("Remove events, summaries, and diagnostic images")
        .activatable(true)
        .build();
    delete_row.add_css_class("error");
    privacy_group.add(&delete_row);
    content.append(&privacy_group);

    let today_label = gtk::Label::builder()
        .label("Today · No classified time")
        .halign(gtk::Align::Start)
        .wrap(true)
        .build();
    let last_sample_label = gtk::Label::builder()
        .label("No successful camera sample")
        .halign(gtk::Align::Start)
        .build();
    let message_label = gtk::Label::builder()
        .label("Tracking starts only when you select Start.")
        .halign(gtk::Align::Start)
        .wrap(true)
        .build();
    message_label.add_css_class("footer-message");
    content.append(&today_label);
    content.append(&last_sample_label);
    content.append(&message_label);

    let clamp = adw::Clamp::builder()
        .maximum_size(720)
        .child(&content)
        .build();
    let scroller = gtk::ScrolledWindow::builder()
        .hscrollbar_policy(gtk::PolicyType::Never)
        .child(&clamp)
        .build();
    let toolbar_view = adw::ToolbarView::new();
    toolbar_view.add_top_bar(&header);
    toolbar_view.set_content(Some(&scroller));
    let toast_overlay = adw::ToastOverlay::new();
    toast_overlay.set_child(Some(&toolbar_view));
    window.set_content(Some(&toast_overlay));

    let action_widgets = [
        start_button.clone().upcast::<gtk::Widget>(),
        pause_button.clone().upcast(),
        pause_for_button.clone().upcast(),
        end_button.clone().upcast(),
        save_camera_button.clone().upcast(),
        camera_dropdown.clone().upcast(),
        refresh_cameras_button.clone().upcast(),
        models_button.clone().upcast(),
        preview_button.clone().upcast(),
        calibrate_button.clone().upcast(),
        diagnostic_row.clone().upcast(),
        open_session_row.clone().upcast(),
        open_data_row.clone().upcast(),
        delete_row.clone().upcast(),
        history_button.clone().upcast(),
    ]
    .to_vec();

    Ui {
        window,
        toast_overlay,
        status_card,
        status_label,
        status_duration,
        session_summary,
        metric_values,
        today_label,
        last_sample_label,
        message_label,
        camera_dropdown,
        camera_indices,
        diagnostic_row,
        start_button,
        pause_button,
        pause_for_button,
        end_button,
        save_camera_button,
        refresh_cameras_button,
        models_button,
        preview_button,
        calibrate_button,
        open_session_row,
        open_data_row,
        delete_row,
        history_button,
        action_widgets,
    }
}

fn connect_actions(ui: &Rc<Ui>, state: &Rc<AppState>) {
    connect_button(
        ui,
        state,
        &ui.start_button,
        Action::Start,
        "start",
        json!({}),
        "Starting tracking…",
    );
    connect_button(
        ui,
        state,
        &ui.pause_button,
        Action::Pause,
        "pause",
        json!({}),
        "Pausing tracking…",
    );
    connect_button(
        ui,
        state,
        &ui.pause_for_button,
        Action::PauseFor,
        "pause_for",
        json!({"seconds": 900}),
        "Pausing tracking…",
    );
    connect_button(
        ui,
        state,
        &ui.end_button,
        Action::EndSession,
        "end_session",
        json!({}),
        "Ending the session…",
    );
    connect_button(
        ui,
        state,
        &ui.models_button,
        Action::DownloadModels,
        "download_models",
        json!({}),
        "Downloading models…",
    );
    connect_button(
        ui,
        state,
        &ui.preview_button,
        Action::Preview,
        "preview",
        json!({}),
        "Opening the camera preview…",
    );
    connect_button(
        ui,
        state,
        &ui.calibrate_button,
        Action::Calibrate,
        "calibrate",
        json!({}),
        "Face the main screen and keep your head still…",
    );

    let save_ui = Rc::clone(ui);
    let save_state = Rc::clone(state);
    ui.save_camera_button.connect_clicked(move |_| {
        let position = save_ui.camera_dropdown.selected() as usize;
        let Some(camera_index) = save_ui.camera_indices.borrow().get(position).copied() else {
            save_ui.toast("Select an available camera first.");
            return;
        };
        send_action(
            &save_ui,
            &save_state,
            Action::SaveCamera,
            "save_camera_index",
            json!({"camera_index": camera_index}),
            "Saving the camera setting…",
        );
    });

    let refresh_ui = Rc::clone(ui);
    let refresh_state = Rc::clone(state);
    ui.refresh_cameras_button.connect_clicked(move |_| {
        if refresh_state.busy.replace(true) {
            refresh_ui.toast("Wait for the current action to finish.");
            return;
        }
        refresh_ui.set_busy(true);
        refresh_ui.message_label.set_label("Detecting cameras…");
        if !refresh_state.send(EngineRequest {
            kind: RequestKind::Cameras,
            command: "list_cameras",
            arguments: json!({}),
        }) {
            refresh_state.busy.set(false);
            refresh_ui.set_busy(false);
            refresh_ui.toast("Cannot contact the tracking engine.");
        }
    });

    let diagnostic_ui = Rc::clone(ui);
    let diagnostic_state = Rc::clone(state);
    ui.diagnostic_row.connect_active_notify(move |row| {
        if diagnostic_state.changing_diagnostic_switch.get() {
            return;
        }
        let enabled = row.is_active();
        if enabled {
            let dialog = adw::MessageDialog::builder()
                .transient_for(&diagnostic_ui.window)
                .heading("Save diagnostic output?")
                .body("Images can show you, other people, and your room. They stay on this computer and apply only to future sessions.")
                .build();
            dialog.add_response("cancel", "Cancel");
            dialog.add_response("save", "Save images");
            dialog.set_response_appearance("save", adw::ResponseAppearance::Suggested);
            dialog.set_default_response(Some("cancel"));
            dialog.set_close_response("cancel");
            let confirm_ui = Rc::clone(&diagnostic_ui);
            let confirm_state = Rc::clone(&diagnostic_state);
            dialog.connect_response(None, move |dialog, response| {
                if response == "save" {
                    send_action(
                        &confirm_ui,
                        &confirm_state,
                        Action::SaveDiagnostics(true),
                        "save_diagnostic_setting",
                        json!({"enabled": true}),
                        "Enabling diagnostic output…",
                    );
                } else {
                    confirm_state.changing_diagnostic_switch.set(true);
                    confirm_ui.diagnostic_row.set_active(false);
                    confirm_state.changing_diagnostic_switch.set(false);
                }
                dialog.close();
            });
            dialog.present();
        } else {
            send_action(
                &diagnostic_ui,
                &diagnostic_state,
                Action::SaveDiagnostics(false),
                "save_diagnostic_setting",
                json!({"enabled": false}),
                "Disabling diagnostic output…",
            );
        }
    });

    connect_row_action(
        &ui.open_session_row,
        ui,
        state,
        Action::OpenSession,
        "open_session_folder",
    );
    connect_row_action(
        &ui.open_data_row,
        ui,
        state,
        Action::OpenData,
        "open_data_folder",
    );

    let delete_ui = Rc::clone(ui);
    let delete_state = Rc::clone(state);
    ui.delete_row.connect_activated(move |_| {
        let dialog = adw::MessageDialog::builder()
            .transient_for(&delete_ui.window)
            .heading("Delete all local history?")
            .body("This removes events, session summaries, and diagnostic images. This action cannot be undone.")
            .build();
        dialog.add_response("cancel", "Cancel");
        dialog.add_response("delete", "Delete history");
        dialog.set_response_appearance("delete", adw::ResponseAppearance::Destructive);
        dialog.set_default_response(Some("cancel"));
        dialog.set_close_response("cancel");
        let confirm_ui = Rc::clone(&delete_ui);
        let confirm_state = Rc::clone(&delete_state);
        dialog.connect_response(None, move |dialog, response| {
            if response == "delete" {
                send_action(
                    &confirm_ui,
                    &confirm_state,
                    Action::DeleteHistory,
                    "delete_history",
                    json!({}),
                    "Deleting local history…",
                );
            }
            dialog.close();
        });
        dialog.present();
    });

    let history_ui = Rc::clone(ui);
    let history_state = Rc::clone(state);
    ui.history_button.connect_clicked(move |_| {
        history_state.busy.set(true);
        history_ui.set_busy(true);
        history_ui
            .message_label
            .set_label("Loading session history…");
        if !history_state.send(EngineRequest {
            kind: RequestKind::Sessions,
            command: "session_summaries",
            arguments: json!({}),
        }) {
            history_ui.toast("Cannot contact the tracking engine.");
        }
    });
}

fn connect_button(
    ui: &Rc<Ui>,
    state: &Rc<AppState>,
    button: &gtk::Button,
    action: Action,
    command: &'static str,
    arguments: Value,
    pending_message: &'static str,
) {
    let action_ui = Rc::clone(ui);
    let action_state = Rc::clone(state);
    button.connect_clicked(move |_| {
        send_action(
            &action_ui,
            &action_state,
            action.clone(),
            command,
            arguments.clone(),
            pending_message,
        );
    });
}

fn connect_row_action(
    row: &adw::ActionRow,
    ui: &Rc<Ui>,
    state: &Rc<AppState>,
    action: Action,
    command: &'static str,
) {
    let action_ui = Rc::clone(ui);
    let action_state = Rc::clone(state);
    row.connect_activated(move |_| {
        send_action(
            &action_ui,
            &action_state,
            action.clone(),
            command,
            json!({}),
            "Opening the local data folder…",
        );
    });
}

fn send_action(
    ui: &Ui,
    state: &AppState,
    action: Action,
    command: &'static str,
    arguments: Value,
    pending_message: &str,
) {
    if state.busy.replace(true) {
        ui.toast("Wait for the current action to finish.");
        return;
    }
    ui.set_busy(true);
    ui.message_label.set_label(pending_message);
    if !state.send(EngineRequest {
        kind: RequestKind::Action(action),
        command,
        arguments,
    }) {
        state.busy.set(false);
        ui.set_busy(false);
        ui.toast("Cannot contact the tracking engine.");
    }
}

fn request_snapshot(state: &AppState) {
    if state.snapshot_pending.replace(true) {
        return;
    }
    if !state.send(EngineRequest {
        kind: RequestKind::Snapshot,
        command: "snapshot",
        arguments: json!({}),
    }) {
        state.snapshot_pending.set(false);
    }
}

fn handle_response(ui: &Ui, state: &AppState, response: EngineResponse) {
    match response.kind {
        RequestKind::Snapshot => {
            state.snapshot_pending.set(false);
            match response.result.and_then(|value| {
                serde_json::from_value(value)
                    .map_err(|error| format!("Cannot read tracking status: {error}"))
            }) {
                Ok(snapshot) => ui.apply_snapshot(snapshot),
                Err(error) => ui.message_label.set_label(&error),
            }
        }
        RequestKind::Config => match response.result {
            Ok(config) => {
                if let Some(index) = config.get("camera_index").and_then(Value::as_i64) {
                    state.configured_camera_index.set(index);
                }
                if let Some(enabled) = config
                    .get("save_diagnostic_frames")
                    .and_then(Value::as_bool)
                {
                    state.changing_diagnostic_switch.set(true);
                    ui.diagnostic_row.set_active(enabled);
                    state.changing_diagnostic_switch.set(false);
                }
            }
            Err(error) => ui.message_label.set_label(&error),
        },
        RequestKind::Cameras => {
            state.busy.set(false);
            ui.set_busy(false);
            match response.result {
                Ok(value) => {
                    if let Err(error) =
                        ui.apply_camera_list(value, state.configured_camera_index.get())
                    {
                        ui.message_label.set_label(&error);
                    } else {
                        ui.message_label.set_label("Available cameras updated.");
                    }
                }
                Err(error) => {
                    ui.message_label
                        .set_label(&format!("Cannot detect cameras: {error}"));
                    ui.toast("Camera discovery failed.");
                }
            }
        }
        RequestKind::ModelsReady => {
            if matches!(response.result, Ok(Value::Bool(false))) {
                ui.message_label
                    .set_label("Download the local models before your first session.");
            }
        }
        RequestKind::Sessions => {
            state.busy.set(false);
            ui.set_busy(false);
            match response.result {
                Ok(value) => show_session_history(&ui.window, value),
                Err(error) => ui.toast(&format!("Cannot read session history: {error}")),
            }
        }
        RequestKind::Action(action) => {
            state.busy.set(false);
            ui.set_busy(false);
            match response.result {
                Ok(result) => {
                    ui.message_label
                        .set_label(&action.completion_message(&result));
                    if let Action::SaveCamera = &action
                        && let Some(index) = result.get("camera_index").and_then(Value::as_i64)
                    {
                        state.configured_camera_index.set(index);
                    }
                    if let Action::SaveDiagnostics(enabled) = action {
                        state.changing_diagnostic_switch.set(true);
                        ui.diagnostic_row.set_active(enabled);
                        state.changing_diagnostic_switch.set(false);
                    }
                    request_snapshot(state);
                }
                Err(error) => {
                    if let Action::SaveDiagnostics(enabled) = action {
                        state.changing_diagnostic_switch.set(true);
                        ui.diagnostic_row.set_active(!enabled);
                        state.changing_diagnostic_switch.set(false);
                    }
                    ui.message_label.set_label(&error);
                    ui.toast(&error);
                }
            }
        }
        RequestKind::Shutdown => {}
    }
}

fn show_session_history(parent: &adw::ApplicationWindow, value: Value) {
    let window = adw::Window::builder()
        .title("Session history")
        .transient_for(parent)
        .default_width(620)
        .default_height(680)
        .build();
    let header = adw::HeaderBar::new();
    let group = adw::PreferencesGroup::builder()
        .title("Saved sessions")
        .build();
    let sessions = value.as_array().cloned().unwrap_or_default();
    if sessions.is_empty() {
        let page = adw::StatusPage::builder()
            .icon_name("document-open-recent-symbolic")
            .title("No saved sessions")
            .description("Completed sessions will appear here.")
            .build();
        let toolbar = adw::ToolbarView::new();
        toolbar.add_top_bar(&header);
        toolbar.set_content(Some(&page));
        window.set_content(Some(&toolbar));
        window.present();
        return;
    }

    for session in sessions {
        let started = session
            .get("started_at")
            .and_then(Value::as_str)
            .unwrap_or("Unknown time");
        let state = session
            .get("state")
            .and_then(Value::as_str)
            .unwrap_or("unknown");
        let tracked = session
            .get("tracked_seconds")
            .and_then(Value::as_f64)
            .unwrap_or_default();
        let focus = session.get("focused_active_ratio").and_then(Value::as_f64);
        let phone = session
            .get("status_seconds")
            .and_then(Value::as_object)
            .and_then(|statuses| statuses.get("POSSIBLE_PHONE_USE"))
            .and_then(Value::as_f64)
            .unwrap_or_default();
        let row = adw::ActionRow::builder()
            .title(format!("{} · {}", display_time(started), capitalize(state)))
            .subtitle(format!(
                "Duration {} · Focus {} · Phone {}",
                format_duration(tracked),
                format_ratio(focus),
                format_duration(phone)
            ))
            .build();
        group.add(&row);
    }
    let clamp = adw::Clamp::builder()
        .maximum_size(680)
        .child(&group)
        .build();
    clamp.set_margin_top(24);
    clamp.set_margin_bottom(24);
    clamp.set_margin_start(18);
    clamp.set_margin_end(18);
    let scroller = gtk::ScrolledWindow::builder().child(&clamp).build();
    let toolbar = adw::ToolbarView::new();
    toolbar.add_top_bar(&header);
    toolbar.set_content(Some(&scroller));
    window.set_content(Some(&toolbar));
    window.present();
}

fn status_label(status: &str) -> &'static str {
    match status {
        "FOCUSED_SCREEN" => "Focused",
        "POSSIBLE_PHONE_USE" => "Possible phone use",
        "LOOKING_DOWN" => "Looking down · uncertain",
        "LOOKING_AWAY" => "Looking away · person visible",
        "AWAY" => "Away · no person visible",
        "SYSTEM_IDLE" => "System idle",
        "UNCERTAIN" => "Uncertain",
        "PAUSED" => "Paused",
        "CAMERA_ERROR" => "Camera error",
        _ => "Unknown",
    }
}

fn format_duration(seconds: f64) -> String {
    let total = seconds.max(0.0).round() as u64;
    let hours = total / 3600;
    let minutes = (total % 3600) / 60;
    let remaining = total % 60;
    if hours > 0 {
        format!("{hours}h {minutes:02}m")
    } else if minutes > 0 {
        format!("{minutes}m {remaining:02}s")
    } else {
        format!("{remaining}s")
    }
}

fn format_ratio(value: Option<f64>) -> String {
    value
        .map(|ratio| format!("{:.0}%", ratio * 100.0))
        .unwrap_or_else(|| "Not enough data".into())
}

fn display_time(timestamp: &str) -> &str {
    timestamp.get(11..19).unwrap_or(timestamp)
}

fn capitalize(value: &str) -> String {
    let mut characters = value.chars();
    match characters.next() {
        Some(first) => first.to_uppercase().collect::<String>() + characters.as_str(),
        None => String::new(),
    }
}

fn load_styles() {
    let provider = gtk::CssProvider::new();
    provider.load_from_data(include_str!("style.css"));
    if let Some(display) = gtk::gdk::Display::default() {
        gtk::style_context_add_provider_for_display(
            &display,
            &provider,
            gtk::STYLE_PROVIDER_PRIORITY_APPLICATION,
        );
    }
}

fn config_argument() -> Option<PathBuf> {
    let arguments: Vec<_> = env::args_os().collect();
    arguments
        .windows(2)
        .find(|pair| pair[0] == "--config")
        .map(|pair| PathBuf::from(&pair[1]))
}

#[cfg(target_os = "macos")]
fn configure_bundled_resources() {
    let Ok(executable) = env::current_exe() else {
        return;
    };
    let Some(contents) = executable.parent().and_then(Path::parent) else {
        return;
    };
    let share = contents.join("Resources").join("share");
    if !share.is_dir() {
        return;
    }
    // This runs before GTK starts or any worker thread exists.
    unsafe {
        env::set_var("XDG_DATA_DIRS", &share);
        env::set_var(
            "GSETTINGS_SCHEMA_DIR",
            share.join("glib-2.0").join("schemas"),
        );
    }
}

#[cfg(not(target_os = "macos"))]
fn configure_bundled_resources() {}

fn main() -> glib::ExitCode {
    configure_bundled_resources();
    let config_path = config_argument();
    let application = adw::Application::builder().application_id(APP_ID).build();
    application.connect_activate(move |application| {
        if let Some(window) = application.active_window() {
            window.present();
            return;
        }
        build_ui(application, config_path.clone());
    });
    application.run()
}
