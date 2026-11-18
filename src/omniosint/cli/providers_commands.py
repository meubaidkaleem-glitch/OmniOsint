"""`omniosint providers ...`

The catalogue lists what is planned; adapters are what can collect. In Phase 2
the only adapter is the simulated provider, disabled unless enabled for
testing. Nothing here pretends to contact a provider that has no adapter.
"""

from __future__ import annotations

from typing import Annotated, Any

import typer
from rich.table import Table

from omniosint.cli.common import (
    EXIT_USAGE,
    console,
    emit_json,
    escape,
    fail,
    load_runtime,
    run_async,
    use_json,
)
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.errors import PLANNED_MESSAGE
from omniosint.core.features import PHASES
from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue
from omniosint.providers.registry import ProviderState

app = typer.Typer(help="Provider catalogue, adapters and their health.", no_args_is_help=True)


@app.command("list")
def list_providers(
    category: Annotated[
        str | None, typer.Option(help="Only this category (see --json for keys).")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """List the provider catalogue with each entry's real status."""
    use_json(json_output)
    catalogue = load_catalogue()
    if category is not None and category not in CATEGORY_LABELS:
        fail(
            f"Unknown category {category!r}.",
            hint="Categories: " + ", ".join(CATEGORY_LABELS),
            code=EXIT_USAGE,
        )
    entries = [p for p in catalogue.providers if category is None or p.category == category]
    counts = catalogue.status_counts()
    if json_output:
        emit_json(
            {
                "ok": True,
                "counts": {"total": len(catalogue.providers), **counts},
                "providers": [
                    {
                        "id": entry.id,
                        "name": entry.name,
                        "category": entry.category,
                        "access": entry.access,
                        "auth": entry.auth,
                        "phase": entry.phase,
                        "status": entry.status,
                        "status_message": entry.status_message,
                    }
                    for entry in entries
                ],
                "adapters": [
                    {
                        "id": state.id,
                        "name": state.name,
                        "status": state.status,
                        "message": state.message,
                        "simulated": state.simulated,
                    }
                    for state in _adapter_states()
                ],
            }
        )
        return

    table = Table("Provider", "Category", "Access", "Phase", "Status")
    for entry in entries:
        colour = {"planned": "yellow", "available": "green", "excluded": "dim"}[entry.status]
        table.add_row(
            escape(entry.name),
            entry.category_label,
            entry.access_label,
            str(entry.phase),
            f"[{colour}]{entry.status.capitalize()}[/{colour}]",
        )
    console.print(table)
    console.print(
        f"{len(catalogue.providers)} entries: {counts['available']} available, "
        f"{counts['planned']} planned, {counts['excluded']} excluded."
    )
    if counts["available"] == 0:
        console.print(
            f"[yellow]{PLANNED_MESSAGE}[/yellow] No real provider can be configured or "
            "queried yet. The first integrations arrive in Phases 4 to 6 (docs/PROVIDERS.md)."
        )
    states = _adapter_states()
    if states:
        console.print()
        adapters = Table("Adapter", "Status", "Note")
        for state in states:
            colour = {"available": "green", "not_configured": "yellow"}.get(state.status, "dim")
            note = "simulated test data" if state.simulated else ""
            adapters.add_row(
                escape(state.name),
                f"[{colour}]{state.status}[/{colour}]",
                escape(note or state.message),
            )
        console.print(adapters)


def _adapter_states() -> list[ProviderState]:
    runtime = load_runtime()
    registry = run_async(IntelRuntime.build(runtime.settings, runtime.paths)).registry
    return [state for state in registry.states() if state.adapter is not None]


@app.command("test")
def check_providers(
    provider_id: Annotated[
        str | None, typer.Argument(help="Provider identifier; every usable adapter when omitted.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Run the health check of provider adapters.

    Catalogue entries without an adapter are reported as planned and are not
    tested. The exit status is 0 only when every tested adapter is healthy, and
    2 when nothing could be tested, so scripts never mistake that for success.
    """
    use_json(json_output)
    runtime = load_runtime()

    async def work() -> list[dict[str, Any]]:
        intel = await IntelRuntime.build(runtime.settings, runtime.paths)
        try:
            states = intel.registry.states()
            if provider_id is not None:
                states = [state for state in states if state.id == provider_id]
                if not states:
                    fail(f"No provider {provider_id!r}.", code=EXIT_USAGE)
            results = []
            for state in states:
                if state.adapter is None or not state.runnable:
                    entry = state.entry
                    message = state.message
                    if state.status == "planned" and entry is not None:
                        message = (
                            f"{PLANNED_MESSAGE} Scheduled for Phase {entry.phase}: "
                            f"{PHASES[entry.phase]}."
                        )
                    results.append(
                        {
                            "id": state.id,
                            "name": state.name,
                            "tested": False,
                            "status": state.status,
                            "message": message,
                        }
                    )
                    continue
                health = await intel.manager.health(state.id)
                results.append(
                    {
                        "id": state.id,
                        "name": state.name,
                        "tested": True,
                        "status": health.status,
                        "message": health.detail,
                        "simulated": state.simulated,
                        "latency_ms": health.latency_ms,
                    }
                )
            return results
        finally:
            await intel.aclose()

    results = run_async(work())
    tested = [result for result in results if result["tested"]]
    healthy = all(result["status"] == "ok" for result in tested)
    if json_output:
        emit_json({"ok": bool(tested) and healthy, "tested": len(tested), "results": results})
    else:
        for result in results:
            label = (
                "OK"
                if result["tested"] and result["status"] == "ok"
                else ("FAILED" if result["tested"] else "NOT TESTED")
            )
            colour = {"OK": "green", "FAILED": "red"}.get(label, "yellow")
            console.print(
                f"[{colour}]{label}[/{colour}] {escape(str(result['name']))}: "
                f"{escape(str(result['message']))}"
            )
        if not tested:
            console.print("No provider was tested: no usable adapter is installed and enabled.")
    if not tested:
        raise typer.Exit(EXIT_USAGE)
    if not healthy:
        raise typer.Exit(1)
