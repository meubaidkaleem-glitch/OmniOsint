//! Drives a real OmniOSINT installation through start, probe and stop.
//!
//! Runs only when OMNIOSINT_DESKTOP_TEST_ROOT names an installed program folder
//! whose configuration (environment or data directory) points at a usable,
//! disposable database.

use std::path::PathBuf;
use std::time::Duration;

use omniosint_backend_control::{probe_live, Installation};

#[test]
fn starts_probes_and_stops_a_real_installation() {
    let Some(root) = std::env::var_os("OMNIOSINT_DESKTOP_TEST_ROOT") else {
        eprintln!("skipped: OMNIOSINT_DESKTOP_TEST_ROOT is not set");
        return;
    };
    let installation = Installation::locate_in(&[PathBuf::from(root)]).expect("installation");

    let info = installation.start().expect("start");
    assert!(info.url.starts_with("http://127.0.0.1:"), "{info:?}");
    assert!(
        probe_live(&info.url, Duration::from_secs(3)),
        "backend did not answer"
    );

    let again = installation.start().expect("second start");
    assert!(
        again.already_running,
        "a second start attaches to the running instance"
    );

    installation.stop().expect("stop");
    assert!(
        !probe_live(&info.url, Duration::from_secs(1)),
        "backend still answers after stop"
    );
}
