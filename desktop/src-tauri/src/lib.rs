//! OmniOSINT desktop shell.
//!
//! Shows a bundled status page while it starts the local backend through the
//! OmniOSINT command line, then loads the web interface from 127.0.0.1. It
//! watches the backend, raises a system notification and returns to the status
//! page if the backend stops, and stops the backend on exit if it was the one
//! that started it.

use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use omniosint_backend_control::{probe_live, ControlError, Installation, StartInfo};
use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, Url};
use tauri_plugin_notification::NotificationExt;

const MONITOR_INTERVAL: Duration = Duration::from_secs(5);
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);
const FAILURES_BEFORE_STOPPED: u32 = 2;

#[derive(Debug, Clone, Default, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
enum ShellState {
    #[default]
    Starting,
    Running {
        url: String,
    },
    Failed {
        message: String,
        hint: Option<String>,
    },
    Stopped {
        message: String,
    },
}

#[derive(Default)]
struct Shared {
    state: Mutex<ShellState>,
    installation: Mutex<Option<Installation>>,
    started_by_shell: Mutex<bool>,
    status_page: Mutex<Option<Url>>,
    /// Increases on every (re)start so a stale monitor thread ends itself.
    generation: Mutex<u64>,
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    // A panic in another thread must not take the whole shell down.
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn set_state(shared: &Shared, state: ShellState) {
    *lock(&shared.state) = state;
}

fn show_status_page(app: &AppHandle, shared: &Shared) {
    let page = lock(&shared.status_page).clone();
    if let (Some(window), Some(page)) = (app.get_webview_window("main"), page) {
        let _ = window.navigate(page);
    }
}

fn notify(app: &AppHandle, title: &str, body: &str) {
    let _ = app.notification().builder().title(title).body(body).show();
}

fn installation(shared: &Shared) -> Result<Installation, ControlError> {
    if let Some(found) = lock(&shared.installation).clone() {
        return Ok(found);
    }
    let executable = std::env::current_exe().unwrap_or_default();
    let found = Installation::locate(&executable)?;
    *lock(&shared.installation) = Some(found.clone());
    Ok(found)
}

fn start_backend(app: AppHandle) {
    thread::spawn(move || {
        let shared = app.state::<Arc<Shared>>().inner().clone();
        set_state(&shared, ShellState::Starting);
        let generation = {
            let mut generation = lock(&shared.generation);
            *generation += 1;
            *generation
        };
        let result: Result<StartInfo, ControlError> =
            installation(&shared).and_then(|found| found.start());
        match result {
            Ok(info) => {
                *lock(&shared.started_by_shell) = !info.already_running;
                set_state(
                    &shared,
                    ShellState::Running {
                        url: info.url.clone(),
                    },
                );
                match (app.get_webview_window("main"), Url::parse(&info.open_url)) {
                    (Some(window), Ok(target)) => {
                        let _ = window.navigate(target);
                    }
                    _ => set_state(
                        &shared,
                        ShellState::Failed {
                            message: "The interface address could not be opened.".into(),
                            hint: Some(info.open_url.clone()),
                        },
                    ),
                }
                monitor_backend(app.clone(), info.url, generation);
            }
            Err(error) => set_state(
                &shared,
                ShellState::Failed {
                    message: error.message,
                    hint: error.hint,
                },
            ),
        }
    });
}

fn monitor_backend(app: AppHandle, base_url: String, generation: u64) {
    thread::spawn(move || {
        let shared = app.state::<Arc<Shared>>().inner().clone();
        let mut failures = 0;
        loop {
            thread::sleep(MONITOR_INTERVAL);
            if *lock(&shared.generation) != generation {
                return;
            }
            if probe_live(&base_url, PROBE_TIMEOUT) {
                failures = 0;
                continue;
            }
            failures += 1;
            if failures < FAILURES_BEFORE_STOPPED {
                continue;
            }
            set_state(
                &shared,
                ShellState::Stopped {
                    message: "The OmniOSINT service stopped responding.".into(),
                },
            );
            show_status_page(&app, &shared);
            notify(
                &app,
                "OmniOSINT stopped",
                "The local OmniOSINT service is no longer running.",
            );
            return;
        }
    });
}

#[tauri::command]
fn desktop_state(shared: tauri::State<'_, Arc<Shared>>) -> ShellState {
    lock(&shared.state).clone()
}

#[tauri::command]
fn retry_start(app: AppHandle) {
    start_backend(app);
}

fn stop_if_ours(shared: &Shared) {
    if !*lock(&shared.started_by_shell) {
        return;
    }
    // End the monitor first so that it does not report the planned stop.
    *lock(&shared.generation) += 1;
    if let Some(found) = lock(&shared.installation).clone() {
        let _ = found.stop();
    }
}

pub fn run() {
    let shared = Arc::new(Shared::default());
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_notification::init())
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![desktop_state, retry_start])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let shared = app.state::<Arc<Shared>>();
                *lock(&shared.status_page) = window.url().ok();
            }
            start_backend(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the OmniOSINT desktop shell could not be created");

    app.run(move |_handle, event| {
        if let RunEvent::Exit = event {
            stop_if_ours(&shared);
        }
    });
}
