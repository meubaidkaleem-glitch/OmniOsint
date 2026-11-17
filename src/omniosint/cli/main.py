"""`omniosint` command-line interface.

The CLI uses the same service layer as the HTTP API. Commands for features that
are not built yet exist only to say so: they print the planned status and exit
with a non-zero code.
"""

from __future__ import annotations

import contextlib
import json
import sys
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from omniosint import __version__
from omniosint.cli import backup_commands, db_commands, providers_commands
from omniosint.cli.admin_commands import (
    admin_app,
    config_app,
    pending_setup_token,
    secrets_app,
    setup_url,
)
from omniosint.cli.common import (
    EXIT_FAILURE,
    console,
    emit_json,
    error_console,
    escape,
    exit_code_for,
    load_runtime,
    planned,
    report_error,
    run_async,
    use_json,
)
from omniosint.core.config import load_settings
from omniosint.core.errors import OmniError
from omniosint.core.paths import AppPaths
from omniosint.runtime import supervisor
from omniosint.system.doctor import CheckStatus, run_doctor, summarize

PLANNED_PANEL = "Planned (not yet implemented)"

app = typer.Typer(
    name="omniosint",
    help="OmniOSINT - evidence-driven OSINT and intelligence investigation platform.",
    no_args_is_help=True,
    add_completion=False,
    # Rich tracebacks print local variables, which may hold secrets.
    pretty_exceptions_enable=False,
)
app.add_typer(db_commands.app, name="db")
app.add_typer(admin_app, name="admin")
app.add_typer(secrets_app, name="secrets")
app.add_typer(config_app, name="config")
app.add_typer(backup_commands.app, name="backup")
app.add_typer(providers_commands.app, name="providers")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"OmniOSINT {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version_callback, is_eager=True, help="Show the version."
        ),
    ] = False,
) -> None:
    """OmniOSINT command-line interface."""


# --------------------------------------------------------------------------- lifecycle
def _print_status(report: supervisor.StatusReport) -> None:
    if not report.processes:
        console.print("OmniOSINT is [bold]not running[/bold].")
        return
    table = Table("Process", "PID", "State", "Log")
    for process in report.processes:
        table.add_row(
            process.name,
            str(process.pid),
            "[green]running[/green]" if process.running else "[red]stopped[/red]",
            escape(process.log_file),
        )
    console.print(table)
    if report.health is None:
        reason = f" ({report.health_error})" if report.health_error else ""
        console.print(f"Health: [red]no response[/red] from {report.url}{escape(reason)}")
        return
    colour = {"ok": "green", "degraded": "yellow"}.get(str(report.health.get("status")), "red")
    console.print(f"Health: [{colour}]{report.health.get('status')}[/{colour}] at {report.url}")
    for component in report.health.get("components", []):
        marker = {"ok": "green", "not_configured": "dim", "degraded": "yellow"}.get(
            str(component.get("status")), "red"
        )
        console.print(
            f"  [{marker}]{component.get('status')!s:<15}[/{marker}] {component.get('label')}"
        )


@app.command()
def start(
    no_wait: Annotated[
        bool, typer.Option("--no-wait", help="Return without waiting for readiness.")
    ] = False,
    open_browser: Annotated[
        bool, typer.Option("--open", help="Open the interface in the default browser.")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Start the API and the background worker."""
    use_json(json_output)
    runtime = load_runtime()
    result = supervisor.start(runtime.settings, runtime.paths, wait=not no_wait)
    token = run_async(pending_setup_token(runtime))
    url = result.state.url
    open_url = setup_url(url, token)

    if json_output:
        emit_json(
            {
                "ok": True,
                "already_running": result.already_running,
                "url": url,
                "open_url": open_url,
                "setup_required": token is not None,
                "status": result.status.to_dict(),
            }
        )
    else:
        if result.already_running:
            console.print(f"OmniOSINT is already running at {url}")
        else:
            console.print(f"[green]OmniOSINT started[/green] at {url}")
        _print_status(result.status)
        if token is not None:
            console.print("\n[bold]First-run setup is pending.[/bold] Open:")
            console.print(f"  {escape(open_url)}")
        if not result.status.healthy and not no_wait:
            console.print("[yellow]The application started but is not fully healthy.[/yellow]")

    if open_browser:
        with contextlib.suppress(webbrowser.Error):
            webbrowser.open(open_url)


@app.command()
def stop(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Stop the API and the background worker."""
    use_json(json_output)
    runtime = load_runtime()
    result = supervisor.stop(runtime.settings, runtime.paths)
    if json_output:
        emit_json(
            {
                "ok": True,
                "was_running": result.was_running,
                "stopped": result.stopped,
                "forced": result.forced,
            }
        )
        return
    if not result.was_running:
        console.print("OmniOSINT was not running.")
        return
    console.print(f"[green]OmniOSINT stopped[/green] ({', '.join(result.stopped)}).")
    if result.forced:
        console.print(
            f"[yellow]Had to force:[/yellow] {', '.join(result.forced)} did not stop in time."
        )


@app.command()
def restart(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Stop, then start again."""
    use_json(json_output)
    runtime = load_runtime()
    supervisor.stop(runtime.settings, runtime.paths)
    result = supervisor.start(runtime.settings, runtime.paths)
    if json_output:
        emit_json({"ok": True, "url": result.state.url, "status": result.status.to_dict()})
        return
    console.print(f"[green]OmniOSINT restarted[/green] at {result.state.url}")
    _print_status(result.status)


@app.command()
def status(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit with status 1 unless running and healthy.")
    ] = False,
) -> None:
    """Show whether OmniOSINT is running and healthy."""
    use_json(json_output)
    runtime = load_runtime()
    report = supervisor.status(runtime.settings, runtime.paths)
    if json_output:
        emit_json({"ok": True, **report.to_dict()})
    else:
        _print_status(report)
    if check and not report.healthy:
        raise typer.Exit(EXIT_FAILURE)


@app.command()
def serve(
    reload: Annotated[
        bool, typer.Option("--reload", help="Restart on code changes (development).")
    ] = False,
) -> None:
    """Run the API in the foreground (used by `start`, and for development)."""
    from omniosint.runtime.server import run_api

    paths = AppPaths.resolve()
    paths.ensure()
    run_api(load_settings(paths), paths, reload=reload)


@app.command()
def worker() -> None:
    """Run the background worker in the foreground (used by `start`)."""
    from omniosint.workers.worker import run_worker

    paths = AppPaths.resolve()
    paths.ensure()
    run_worker(load_settings(paths), paths)


# --------------------------------------------------------------------------- diagnostics
@app.command()
def doctor(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check the installation: platform, configuration, database, tools."""
    use_json(json_output)
    paths = AppPaths.resolve()
    paths.ensure()
    settings = None
    config_error: OmniError | None = None
    try:
        settings = load_settings(paths)
    except OmniError as exc:
        config_error = exc

    checks = run_doctor(settings, paths, config_error)
    summary = summarize(checks)
    if json_output:
        emit_json(
            {
                "ok": summary["fail"] == 0,
                "summary": summary,
                "checks": [item.to_dict() for item in checks],
            }
        )
    else:
        styles = {
            CheckStatus.OK: "[green]OK  [/green]",
            CheckStatus.WARN: "[yellow]WARN[/yellow]",
            CheckStatus.FAIL: "[red]FAIL[/red]",
            CheckStatus.INFO: "[dim]INFO[/dim]",
        }
        for item in checks:
            console.print(f"{styles[item.status]}  {item.name}: {escape(item.message)}")
            if item.hint and item.status in (CheckStatus.WARN, CheckStatus.FAIL):
                console.print(f"      [dim]{escape(item.hint)}[/dim]")
        console.print(
            f"\n{summary['ok']} ok, {summary['warn']} warning(s), {summary['fail']} failure(s)."
        )
    if summary["fail"]:
        raise typer.Exit(EXIT_FAILURE)


@app.command("openapi")
def export_openapi(
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="File to write (default: stdout).")
    ] = None,
) -> None:
    """Export the OpenAPI description of the HTTP API."""
    from omniosint.api.app import create_app

    document = create_app(load_settings(use_files=False), manage_lifespan=False).openapi()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8", newline="\n")
        console.print(f"Wrote {escape(str(output))}")


# --------------------------------------------------------------------------- planned
@app.command(rich_help_panel=PLANNED_PANEL)
def search(
    input_value: Annotated[str | None, typer.Option("--input", help="Indicator.")] = None,
) -> None:
    """Classify an indicator and preview a collection plan (Phase 2)."""
    planned("Universal search", 2)


@app.command(rich_help_panel=PLANNED_PANEL)
def investigate(
    input_value: Annotated[str | None, typer.Option("--input", help="Indicator.")] = None,
) -> None:
    """Run an investigation on an indicator (Phases 2 to 4)."""
    planned("Investigations", 3)


cases_app = typer.Typer(help="Investigation cases (Phase 3).", no_args_is_help=True)
reports_app = typer.Typer(help="Reports (Phase 13).", no_args_is_help=True)
report_app = typer.Typer(help="Report generation (Phase 13).", no_args_is_help=True)
graph_app = typer.Typer(help="Relationship graph (Phase 7).", no_args_is_help=True)
monitoring_app = typer.Typer(help="Monitoring and alerts (Phase 11).", no_args_is_help=True)
app.add_typer(cases_app, name="cases", rich_help_panel=PLANNED_PANEL)
app.add_typer(reports_app, name="reports", rich_help_panel=PLANNED_PANEL)
app.add_typer(report_app, name="report", rich_help_panel=PLANNED_PANEL)
app.add_typer(graph_app, name="graph", rich_help_panel=PLANNED_PANEL)
app.add_typer(monitoring_app, name="monitoring", rich_help_panel=PLANNED_PANEL)


@cases_app.command("list")
def cases_list() -> None:
    """List investigation cases (Phase 3)."""
    planned("Case management", 3)


@reports_app.command("list")
def reports_list() -> None:
    """List generated reports (Phase 13)."""
    planned("Reporting", 13)


@report_app.command("generate")
def report_generate(
    case: Annotated[str | None, typer.Option("--case", help="Case identifier.")] = None,
    output_format: Annotated[str, typer.Option("--format", help="pdf, html or json.")] = "pdf",
) -> None:
    """Generate a report for a case (Phase 13)."""
    planned("Report generation", 13)


@graph_app.command("export")
def graph_export(
    case: Annotated[str | None, typer.Option("--case", help="Case identifier.")] = None,
    output_format: Annotated[str, typer.Option("--format", help="graphml, json ...")] = "graphml",
) -> None:
    """Export a case graph (Phase 7)."""
    planned("Graph export", 7)


@monitoring_app.command("list")
def monitoring_list() -> None:
    """List monitoring rules (Phase 11)."""
    planned("Monitoring", 11)


# --------------------------------------------------------------------------- entry point
def main() -> None:
    # Never let an unencodable character (for example a dash on a legacy
    # Windows code page) turn a status message into a crash.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(errors="replace")
    try:
        app()
    except OmniError as exc:
        report_error(exc)
        sys.exit(exit_code_for(exc))
    except KeyboardInterrupt:
        error_console.print("Interrupted.")
        sys.exit(130)


if __name__ == "__main__":
    main()
