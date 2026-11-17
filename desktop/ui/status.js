// Status page of the desktop shell. It polls the shell for the backend state;
// the shell itself navigates the window to the interface once it is ready.
(function () {
  "use strict";

  const invoke = window.__TAURI__ && window.__TAURI__.core && window.__TAURI__.core.invoke;
  const sections = ["starting", "failed", "stopped"];

  function show(id) {
    for (const name of sections) {
      document.getElementById(name).hidden = name !== id;
    }
  }

  function render(state) {
    switch (state.phase) {
      case "failed":
        document.getElementById("failed-message").textContent = state.message || "";
        document.getElementById("failed-hint").textContent = state.hint || "";
        show("failed");
        break;
      case "stopped":
        document.getElementById("stopped-message").textContent = state.message || "";
        show("stopped");
        break;
      default:
        show("starting");
    }
  }

  async function poll() {
    if (!invoke) {
      render({ phase: "failed", message: "This page only works inside the OmniOSINT desktop application." });
      return;
    }
    try {
      render(await invoke("desktop_state"));
    } catch (error) {
      render({ phase: "failed", message: String(error) });
    }
    window.setTimeout(poll, 700);
  }

  async function retry() {
    show("starting");
    try {
      await invoke("retry_start");
    } catch (error) {
      render({ phase: "failed", message: String(error) });
    }
  }

  document.getElementById("retry").addEventListener("click", retry);
  document.getElementById("restart").addEventListener("click", retry);
  poll();
})();
