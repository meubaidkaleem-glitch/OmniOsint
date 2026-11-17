# OmniOSINT desktop shell

A small Tauri 2 application that runs OmniOSINT like a desktop program:

1. It shows a status page while it runs `omniosint start` (configuration,
   database and port checks, then the API and the background worker).
2. When the service is ready it opens the interface from
   `http://127.0.0.1:<port>`, including the first-run setup link on a new
   installation.
3. It checks the service every few seconds. If the service stops, it raises a
   system notification and returns to the status page, which offers to start
   it again.
4. When you close the window it stops the service, but only if it was the one
   that started it.

It contains no lifecycle logic of its own: it calls the same command line as
`start.bat` and `stop.bat`.

## Layout

| Path | Purpose |
|---|---|
| `backend-control/` | Plain Rust library: finds the installation, runs `omniosint start/stop`, probes health. No Tauri dependency, tested on every platform |
| `src-tauri/` | The Tauri application: window, notifications, the two commands the status page uses |
| `ui/` | The bundled status page (static HTML, no framework) |
| `app-icon.png` | Source for `npm run icons` |

## Finding the installation

In order:

1. the `OMNIOSINT_ROOT` environment variable,
2. `install.json` in the data folder, written by `install.bat` / `install.sh`,
3. the folders above the executable (a shell built inside the project).

## Security

* The bundled status page is the only content with access to the shell's
  commands (`capabilities/default.json`). The OmniOSINT interface loaded from
  127.0.0.1 is a remote origin and gets no IPC access.
* The two commands are declared in an app manifest (`build.rs`), so neither is
  available to a page unless a capability grants it.
* The status page has a strict Content Security Policy.

## Building

Requirements: the Rust toolchain (stable), Node.js 22.22+, and on Windows the
Microsoft C++ build tools and WebView2 (present on current Windows 10 and 11).

```powershell
cd desktop
npm ci
npm run build        # executable and NSIS installer in src-tauri\target\release
npm run build:exe    # executable only
npm run dev          # development run
```

Run the backend tests:

```powershell
cargo test --manifest-path desktop\backend-control\Cargo.toml
# also start, probe and stop a real installation:
$env:OMNIOSINT_DESKTOP_TEST_ROOT = (Resolve-Path .).Path
cargo test --manifest-path desktop\backend-control\Cargo.toml
```

## Status

Basic shell (Phase 1). A tray icon and background monitoring arrive with
monitoring and alerts in Phase 11. The installer bundles only the shell, not
Python or the backend: install OmniOSINT itself with `install.bat` first.
