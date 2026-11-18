"""`omniosint backup ...`"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table

from omniosint.backup import service as backup
from omniosint.cli.common import (
    EXIT_FAILURE,
    EXIT_USAGE,
    console,
    emit_json,
    escape,
    fail,
    load_runtime,
    use_json,
)
from omniosint.runtime import supervisor

app = typer.Typer(
    help="Back up and restore the database and the stored raw responses.", no_args_is_help=True
)


def _size(size_bytes: int) -> str:
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.1f} MiB"
    return f"{size_bytes / 1024:.1f} KiB"


@app.command("create")
def create(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Directory to write the archive to."),
    ] = None,
    label: Annotated[str | None, typer.Option(help="Short label added to the file name.")] = None,
    raw_responses: Annotated[
        bool,
        typer.Option(
            "--raw-responses/--no-raw-responses",
            help="Include the stored raw provider responses (the default).",
        ),
    ] = True,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Create a backup archive (database dump, settings file, raw responses, checksums).

    Archives are not encrypted: keep them somewhere only you can read.
    """
    use_json(json_output)
    runtime = load_runtime()
    info = backup.create_backup(
        runtime.settings,
        runtime.paths,
        output_dir=output,
        label=label,
        include_raw=raw_responses,
    )
    if json_output:
        emit_json({"ok": True, **info.to_dict()})
        return
    console.print(f"[green]Backup created:[/green] {escape(str(info.path))}")
    console.print(
        f"  {_size(info.size_bytes)}, schema revision {info.schema_revision}, "
        f"PostgreSQL {escape(info.server_version)}"
    )
    if info.raw_responses_included:
        console.print(f"  {info.raw_responses} raw responses included")
    else:
        console.print("  Raw responses left out (--no-raw-responses)")
    if info.raw_responses_not_exported:
        console.print(
            f"[yellow]{info.raw_responses_not_exported} stored raw responses could not be read "
            "(missing or damaged) and are not in this backup.[/yellow]"
        )
    console.print(
        "[yellow]This archive is not encrypted.[/yellow] It contains password hashes, all "
        "stored data and the raw provider responses in readable form; keep it on an "
        "encrypted volume."
    )


@app.command("list")
def list_backups(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """List backups in the backup directory, newest first."""
    use_json(json_output)
    runtime = load_runtime()
    items = backup.list_backups(runtime.paths)
    if json_output:
        emit_json(
            {
                "ok": True,
                "directory": str(runtime.paths.backups_dir),
                "backups": [item.to_dict() for item in items],
            }
        )
        return
    if not items:
        console.print(f"No backups in {escape(str(runtime.paths.backups_dir))}.")
        return
    table = Table("File", "Created (UTC)", "Size", "Version", "Schema")
    for item in items:
        table.add_row(
            escape(item.path.name),
            item.created_at.replace("T", " ")[:19],
            _size(item.size_bytes),
            escape(item.app_version),
            str(item.schema_revision),
        )
    console.print(table)
    console.print(f"[dim]{escape(str(runtime.paths.backups_dir))}[/dim]")


@app.command("verify")
def verify(
    archive: Annotated[Path, typer.Argument(help="Backup archive to check.")],
) -> None:
    """Check that an archive is complete and unmodified."""
    info = backup.verify_backup(archive)
    console.print(
        f"[green]Valid backup[/green] created {info.created_at} by version "
        f"{escape(info.app_version)} (schema revision {info.schema_revision})."
    )
    if info.raw_responses_included:
        console.print(f"  {info.raw_responses} raw responses, all matching their hashes")
    elif info.format >= 2:
        console.print("  Raw responses were left out of this backup.")
    else:
        console.print("  This backup predates stored raw responses.")


@app.command("restore")
def restore(
    archive: Annotated[Path, typer.Argument(help="Backup archive to restore.")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
    no_safety_backup: Annotated[
        bool,
        typer.Option("--no-safety-backup", help="Skip the backup of the current data."),
    ] = False,
    restore_settings: Annotated[
        bool,
        typer.Option("--restore-settings", help="Also replace the user settings file."),
    ] = False,
) -> None:
    """Replace the current database content and raw responses with a backup.

    OmniOSINT must be stopped. The current data is backed up first unless
    --no-safety-backup is given, and the database restore either completes
    fully or changes nothing.
    """
    runtime = load_runtime()
    info = backup.verify_backup(archive)

    state = supervisor.read_state(runtime.paths)
    if state is not None and any(supervisor.is_alive(item) for item in state.processes):
        fail(
            "OmniOSINT is running.",
            hint="Stop it first (stop.bat or `omniosint stop`), then restore.",
            code=EXIT_FAILURE,
        )

    console.print(
        f"About to restore [bold]{escape(info.path.name)}[/bold] "
        f"(created {info.created_at}, version {escape(info.app_version)})."
    )
    console.print(
        "[yellow]All current data in the database, and the stored raw responses, will be "
        "replaced.[/yellow]"
        + ("" if no_safety_backup else " A backup of the current data is made first.")
    )
    if not yes and not typer.confirm("Continue?", default=False):
        console.print("Nothing was changed.")
        raise typer.Exit(EXIT_USAGE)

    result = backup.restore_backup(
        runtime.settings,
        runtime.paths,
        archive,
        safety_backup=not no_safety_backup,
        restore_settings=restore_settings,
    )
    console.print(f"[green]Restore complete.[/green] Schema revision {result.schema_revision}.")
    raw = result.raw
    console.print(
        f"Raw responses: {raw.restored} restored, {raw.already_present} already present, "
        f"{raw.removed} no longer referred to and removed."
    )
    if raw.missing:
        console.print(
            f"[yellow]{raw.missing} raw responses the restored data refers to are not in the "
            "backup;[/yellow] their evidence keeps its hashes but the raw content cannot be shown."
        )
    if result.safety_backup is not None:
        console.print(f"The previous data was saved to {escape(str(result.safety_backup.path))}.")
