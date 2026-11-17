//! Control of a local OmniOSINT installation for the desktop shell.
//!
//! Everything here goes through the OmniOSINT command line (`python -m
//! omniosint start|stop|status`), the same lifecycle implementation that the
//! Windows scripts use. This crate has no Tauri dependency so that it can be
//! tested on any platform.

use std::fmt;
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use serde::Deserialize;

/// Environment variable naming the program folder explicitly.
pub const ROOT_ENV: &str = "OMNIOSINT_ROOT";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ControlError {
    pub message: String,
    pub hint: Option<String>,
}

impl ControlError {
    fn new(message: impl Into<String>, hint: Option<String>) -> Self {
        Self {
            message: message.into(),
            hint,
        }
    }
}

impl fmt::Display for ControlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.message)?;
        if let Some(hint) = &self.hint {
            write!(f, " ({hint})")?;
        }
        Ok(())
    }
}

impl std::error::Error for ControlError {}

/// Result of `omniosint start --json`.
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct StartInfo {
    pub url: String,
    pub open_url: String,
    pub already_running: bool,
    pub setup_required: bool,
}

#[derive(Debug, Deserialize)]
struct CliErrorBody {
    message: String,
    hint: Option<String>,
}

#[derive(Debug, Deserialize)]
struct CliFailure {
    error: CliErrorBody,
}

#[derive(Debug, Deserialize)]
struct InstallRecord {
    root: PathBuf,
}

/// A program folder with a working virtual environment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Installation {
    pub root: PathBuf,
    pub python: PathBuf,
}

fn venv_python(root: &Path) -> PathBuf {
    if cfg!(windows) {
        root.join(".venv").join("Scripts").join("python.exe")
    } else {
        root.join(".venv").join("bin").join("python")
    }
}

fn looks_installed(root: &Path) -> bool {
    root.join("pyproject.toml").is_file() && venv_python(root).is_file()
}

/// The data directory, as resolved by the backend (OMNIOSINT_HOME or the per-user default).
pub fn data_directory() -> Option<PathBuf> {
    if let Some(home) = std::env::var_os("OMNIOSINT_HOME") {
        return Some(PathBuf::from(home));
    }
    if cfg!(windows) {
        std::env::var_os("LOCALAPPDATA").map(|base| PathBuf::from(base).join("OmniOSINT"))
    } else {
        std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .or_else(|| {
                std::env::var_os("HOME")
                    .map(|home| PathBuf::from(home).join(".local").join("share"))
            })
            .map(|base| base.join("OmniOSINT"))
    }
}

impl Installation {
    /// Find the program folder. Checked in order: `OMNIOSINT_ROOT`, the folder
    /// recorded by the installer in `<data dir>/install.json`, and the folders
    /// above the running executable (a shell built inside the project).
    pub fn locate(executable: &Path) -> Result<Self, ControlError> {
        let mut candidates: Vec<PathBuf> = Vec::new();
        if let Some(root) = std::env::var_os(ROOT_ENV) {
            candidates.push(PathBuf::from(root));
        }
        if let Some(record) = data_directory().map(|dir| dir.join("install.json")) {
            if let Ok(text) = std::fs::read_to_string(&record) {
                let text = text.trim_start_matches('\u{feff}');
                if let Ok(parsed) = serde_json::from_str::<InstallRecord>(text) {
                    candidates.push(parsed.root);
                }
            }
        }
        candidates.extend(executable.ancestors().skip(1).map(Path::to_path_buf));
        Self::locate_in(&candidates)
    }

    /// The first candidate folder that holds an installation.
    pub fn locate_in(candidates: &[PathBuf]) -> Result<Self, ControlError> {
        candidates
            .iter()
            .find(|root| looks_installed(root))
            .map(|root| Self { root: root.clone(), python: venv_python(root) })
            .ok_or_else(|| {
                ControlError::new(
                    "No OmniOSINT installation was found.",
                    Some(format!(
                        "Run install.bat in the OmniOSINT folder first, or set {ROOT_ENV} to that folder."
                    )),
                )
            })
    }

    fn command(&self, arguments: &[&str]) -> Command {
        let mut command = Command::new(&self.python);
        command
            .args(["-m", "omniosint"])
            .args(arguments)
            .current_dir(&self.root)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        command
    }

    /// Run the command line and return (exit code, stdout, stderr).
    pub fn run(&self, arguments: &[&str]) -> Result<(i32, String, String), ControlError> {
        let output = self.command(arguments).output().map_err(|error| {
            ControlError::new(
                format!("OmniOSINT could not be run: {error}"),
                Some(format!(
                    "Check the Python environment in {}",
                    self.root.display()
                )),
            )
        })?;
        Ok((
            output.status.code().unwrap_or(-1),
            String::from_utf8_lossy(&output.stdout).into_owned(),
            String::from_utf8_lossy(&output.stderr).into_owned(),
        ))
    }

    /// Start the API and the worker (no browser), or attach to a running instance.
    pub fn start(&self) -> Result<StartInfo, ControlError> {
        let (code, stdout, stderr) = self.run(&["start", "--json", "--no-open"])?;
        parse_start(code, &stdout, &stderr)
    }

    /// Stop everything `start` launched.
    pub fn stop(&self) -> Result<(), ControlError> {
        let (code, stdout, stderr) = self.run(&["stop", "--json"])?;
        if code == 0 {
            Ok(())
        } else {
            Err(cli_failure(
                &stdout,
                &stderr,
                "OmniOSINT did not stop cleanly.",
            ))
        }
    }
}

fn cli_failure(stdout: &str, stderr: &str, fallback: &str) -> ControlError {
    if let Ok(failure) = serde_json::from_str::<CliFailure>(stdout.trim()) {
        return ControlError::new(failure.error.message, failure.error.hint);
    }
    let detail = stderr.trim().lines().last().unwrap_or_default().to_string();
    ControlError::new(fallback, (!detail.is_empty()).then_some(detail))
}

/// Interpret the output of `omniosint start --json`.
pub fn parse_start(code: i32, stdout: &str, stderr: &str) -> Result<StartInfo, ControlError> {
    if code == 0 {
        serde_json::from_str::<StartInfo>(stdout.trim()).map_err(|error| {
            ControlError::new(format!("Unexpected answer from OmniOSINT: {error}"), None)
        })
    } else {
        Err(cli_failure(stdout, stderr, "OmniOSINT did not start."))
    }
}

/// `http://host:port` -> socket address.
fn address_of(base_url: &str) -> Option<(String, SocketAddr)> {
    let authority = base_url.strip_prefix("http://")?.split('/').next()?;
    let address = authority.to_socket_addrs().ok()?.next()?;
    Some((authority.to_string(), address))
}

/// True when the liveness endpoint answers 200. Standard library only: the
/// service is on this machine and speaks plain HTTP/1.1.
pub fn probe_live(base_url: &str, timeout: Duration) -> bool {
    let Some((authority, address)) = address_of(base_url) else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&address, timeout) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(timeout));
    let _ = stream.set_write_timeout(Some(timeout));
    let request = format!(
        "GET /api/v1/system/health/live HTTP/1.1\r\nHost: {authority}\r\nConnection: close\r\nAccept: application/json\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut head = [0u8; 32];
    let Ok(read) = stream.read(&mut head) else {
        return false;
    };
    let status_line = String::from_utf8_lossy(&head[..read]);
    status_line.starts_with("HTTP/1.1 200") || status_line.starts_with("HTTP/1.0 200")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    use std::thread;

    #[test]
    fn parses_a_successful_start() {
        let stdout = r#"{"ok": true, "already_running": false, "url": "http://127.0.0.1:8765",
            "open_url": "http://127.0.0.1:8765/setup#token=abc", "setup_required": true, "status": {}}"#;
        let info = parse_start(0, stdout, "").unwrap();
        assert_eq!(info.url, "http://127.0.0.1:8765");
        assert!(info.setup_required);
        assert!(!info.already_running);
    }

    #[test]
    fn reports_the_cli_error_message_and_hint() {
        let stdout = r#"{"ok": false, "error": {"code": "port_in_use", "message": "Port 8765 is busy.", "hint": "Stop the other program."}}"#;
        let error = parse_start(1, stdout, "").unwrap_err();
        assert_eq!(error.message, "Port 8765 is busy.");
        assert_eq!(error.hint.as_deref(), Some("Stop the other program."));
    }

    #[test]
    fn falls_back_to_stderr_when_the_output_is_not_json() {
        let error = parse_start(1, "", "Traceback...\nModuleNotFoundError: x").unwrap_err();
        assert_eq!(error.message, "OmniOSINT did not start.");
        assert_eq!(error.hint.as_deref(), Some("ModuleNotFoundError: x"));
    }

    #[test]
    fn locates_an_installation_by_its_virtual_environment() {
        let folder = tempfile::tempdir().unwrap();
        let root = folder.path().join("omniosint");
        let python = venv_python(&root);
        std::fs::create_dir_all(python.parent().unwrap()).unwrap();
        std::fs::write(&python, b"").unwrap();
        std::fs::write(root.join("pyproject.toml"), b"").unwrap();
        let elsewhere = folder.path().join("elsewhere");
        let found = Installation::locate_in(&[elsewhere, root.clone()]).unwrap();
        assert_eq!(found.root, root);
        assert_eq!(found.python, python);
        assert!(Installation::locate_in(&[folder.path().to_path_buf()]).is_err());
    }

    #[test]
    fn probe_checks_the_status_line() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = thread::spawn(move || {
            for (index, stream) in listener.incoming().take(2).enumerate() {
                let mut stream = stream.unwrap();
                let mut buffer = [0u8; 512];
                let _ = stream.read(&mut buffer);
                let response: &[u8] = if index == 0 {
                    b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\n{}"
                } else {
                    b"HTTP/1.1 503 Service Unavailable\r\ncontent-length: 0\r\n\r\n"
                };
                stream.write_all(response).unwrap();
            }
        });
        let url = format!("http://127.0.0.1:{port}");
        assert!(probe_live(&url, Duration::from_secs(2)));
        assert!(!probe_live(&url, Duration::from_secs(2)));
        server.join().unwrap();
        assert!(!probe_live(
            "http://127.0.0.1:1",
            Duration::from_millis(300)
        ));
        assert!(!probe_live("not a url", Duration::from_millis(300)));
    }
}
