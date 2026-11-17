fn main() {
    // Declaring the app's commands makes Tauri require an explicit permission
    // for each one (see capabilities/default.json) instead of allowing them to
    // every page by default.
    let manifest = tauri_build::AppManifest::new().commands(&["desktop_state", "retry_start"]);
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(manifest))
        .expect("failed to run the Tauri build script");
}
