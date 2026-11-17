"""`omniosint providers ...`

No provider integration exists yet. These commands report the catalogue and
say so plainly; they never pretend to contact a provider.
"""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from omniosint.cli.common import EXIT_USAGE, console, emit_json, escape, fail, use_json
from omniosint.core.errors import PLANNED_MESSAGE
from omniosint.core.features import PHASES
from omniosint.providers.catalog import CATEGORY_LABELS, load_catalogue

app = typer.Typer(help="Provider catalogue and (later) integrations.", no_args_is_help=True)


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
            f"[yellow]{PLANNED_MESSAGE}[/yellow] No provider can be configured or queried "
            "yet. The first integrations arrive in Phases 4 to 6 (docs/PROVIDERS.md)."
        )


@app.command("test")
def test_providers(
    provider_id: Annotated[
        str | None, typer.Argument(help="Catalogue identifier; all providers when omitted.")
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Check provider connectivity.

    There is nothing to test yet: no provider adapter exists. The command lists
    what it would test and exits with a non-zero status so that scripts do not
    mistake this for a successful check.
    """
    use_json(json_output)
    catalogue = load_catalogue()
    if provider_id is not None:
        entry = catalogue.get(provider_id)
        if entry is None:
            fail(f"No provider {provider_id!r} in the catalogue.", code=EXIT_USAGE)
        entries = [entry]
    else:
        entries = list(catalogue.providers)

    results = [
        {
            "id": entry.id,
            "name": entry.name,
            "tested": False,
            "status": entry.status,
            "message": entry.status_message
            if entry.status != "planned"
            else f"{PLANNED_MESSAGE} Scheduled for Phase {entry.phase}: {PHASES[entry.phase]}.",
        }
        for entry in entries
    ]
    if json_output:
        emit_json({"ok": False, "tested": 0, "results": results})
    else:
        for result in results:
            console.print(f"[yellow]NOT TESTED[/yellow] {escape(str(result['name']))}: "
                          f"{escape(str(result['message']))}")
        console.print("No provider was tested: no integration is implemented yet.")
    raise typer.Exit(EXIT_USAGE)
