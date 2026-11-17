"""`omniosint admin`, `omniosint secrets` and `omniosint config`."""

from __future__ import annotations

import sys
from typing import Annotated

import typer
import yaml
from rich.table import Table

from omniosint.audit.service import CLI_ACTOR
from omniosint.auth.passwords import PasswordHasher
from omniosint.auth.permissions import ADMINISTRATOR, BUILTIN_ROLE_NAMES
from omniosint.auth.service import AuthService
from omniosint.cli.common import (
    EXIT_CONFIGURATION,
    EXIT_USAGE,
    Runtime,
    console,
    emit_json,
    escape,
    fail,
    load_runtime,
    open_database,
    prompt_new_secret,
    read_secret_from_stdin,
    run_async,
    use_json,
)
from omniosint.core.config import config_files, load_settings
from omniosint.core.errors import OmniError
from omniosint.core.paths import AppPaths, default_config_dir, project_root
from omniosint.core.secrets import SecretStore, validate_secret_name
from omniosint.users.service import UserService

admin_app = typer.Typer(help="User accounts and first-run setup.", no_args_is_help=True)
secrets_app = typer.Typer(help="Protected local secret store.", no_args_is_help=True)
config_app = typer.Typer(help="Inspect and validate the configuration.", no_args_is_help=True)


def _services(runtime: Runtime) -> tuple[AuthService, UserService]:
    hasher = PasswordHasher(runtime.settings.auth)
    return AuthService(runtime.settings.auth, hasher), UserService(runtime.settings.auth, hasher)


def setup_url(base_url: str, token: str | None) -> str:
    """Address to open in a browser. The token travels in the fragment, which
    browsers do not send to the server and which is not written to logs."""
    return f"{base_url}/setup#token={token}" if token else f"{base_url}/"


async def pending_setup_token(runtime: Runtime) -> str | None:
    """The first-run setup token while no user exists, otherwise ``None``."""
    auth, _users = _services(runtime)
    async with open_database(runtime) as database, database.session() as session:
        return await auth.ensure_setup_token(session, runtime.paths)


# --------------------------------------------------------------------------- admin
@admin_app.command("create-user")
def create_user(
    username: Annotated[str, typer.Argument(help="Sign-in name (lower-case).")],
    role: Annotated[
        list[str] | None,
        typer.Option("--role", "-r", help="Role to assign; repeat for several."),
    ] = None,
    display_name: Annotated[str, typer.Option(help="Name shown in the interface.")] = "",
    email: Annotated[str | None, typer.Option(help="Optional email address.")] = None,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the password from standard input.")
    ] = False,
    require_change: Annotated[
        bool,
        typer.Option(help="Require a new password at first sign-in."),
    ] = False,
) -> None:
    """Create a user directly in the database (no running server needed)."""
    runtime = load_runtime()
    roles = role or [ADMINISTRATOR]
    password = read_secret_from_stdin() if password_stdin else prompt_new_secret("Password")
    _auth, users = _services(runtime)

    async def create() -> str:
        async with open_database(runtime) as database, database.session() as session:
            user = await users.create_user(
                session,
                actor=CLI_ACTOR,
                username=username,
                display_name=display_name,
                email=email,
                password=password,
                roles=roles,
                must_change_password=require_change,
            )
            return user.username

    created = run_async(create())
    runtime.paths.setup_token_file.unlink(missing_ok=True)
    console.print(f"[green]Created user[/green] {escape(created)} with role(s): {', '.join(roles)}.")


@admin_app.command("list-users")
def list_users(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """List user accounts."""
    use_json(json_output)
    runtime = load_runtime()
    _auth, users = _services(runtime)

    async def read() -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        cursor: str | None = None
        async with open_database(runtime) as database, database.session() as session:
            while True:
                page = await users.list_users(session, limit=200, cursor=cursor)
                rows.extend(
                    {
                        "username": user.username,
                        "display_name": user.display_name,
                        "roles": user.role_names,
                        "active": user.is_active,
                        "last_login_at": user.last_login_at,
                    }
                    for user in page.items
                )
                cursor = page.next_cursor
                if cursor is None:
                    return rows

    rows = run_async(read())
    if json_output:
        emit_json({"ok": True, "users": rows})
        return
    if not rows:
        console.print("No users exist yet. Complete first-run setup or run: "
                      "omniosint admin create-user <name>")
        return
    table = Table("Username", "Name", "Roles", "Active", "Last sign-in")
    for row in rows:
        last = row["last_login_at"]
        table.add_row(
            escape(str(row["username"])),
            escape(str(row["display_name"])),
            ", ".join(row["roles"]),  # type: ignore[arg-type]
            "yes" if row["active"] else "no",
            f"{last:%Y-%m-%d %H:%M} UTC" if last else "never",  # type: ignore[str-format]
        )
    console.print(table)


@admin_app.command("reset-password")
def reset_password(
    username: Annotated[str, typer.Argument(help="Account to reset.")],
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read the new password from standard input.")
    ] = False,
    require_change: Annotated[
        bool, typer.Option(help="Require another change at next sign-in.")
    ] = False,
) -> None:
    """Set a new password for a user, end their sessions and clear any lockout."""
    runtime = load_runtime()
    _auth, users = _services(runtime)
    password = read_secret_from_stdin() if password_stdin else prompt_new_secret("New password")

    async def reset() -> None:
        async with open_database(runtime) as database, database.session() as session:
            user = await users.get_by_username(session, username)
            if user is None:
                raise OmniError(f"No user named {username!r} exists.")
            await users.reset_password(
                session,
                user.id,
                actor=CLI_ACTOR,
                new_password=password,
                must_change_password=require_change,
            )

    run_async(reset())
    console.print(f"[green]Password reset[/green] for {escape(username)}. Their sessions were ended.")


@admin_app.command("setup-token")
def setup_token(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Show the first-run setup token and the address to open."""
    use_json(json_output)
    runtime = load_runtime()
    token = run_async(pending_setup_token(runtime))
    base_url = runtime.settings.server.base_url
    if json_output:
        emit_json(
            {
                "ok": True,
                "setup_required": token is not None,
                "setup_token": token,
                "open_url": setup_url(base_url, token),
            }
        )
        return
    if token is None:
        console.print("Setup is complete: a user already exists. Sign in at "
                      f"{base_url}/")
        return
    console.print("First-run setup is pending.")
    console.print(f"  Setup token: [bold]{escape(token)}[/bold]")
    console.print(f"  Open:        {escape(setup_url(base_url, token))}")
    console.print(f"[dim]The token is also stored in {escape(str(runtime.paths.setup_token_file))}[/dim]")


# --------------------------------------------------------------------------- secrets
@secrets_app.command("set")
def secret_set(
    name: Annotated[str, typer.Argument(help="Secret name, for example database.password.")],
    stdin: Annotated[
        bool, typer.Option("--stdin", help="Read the value from standard input.")
    ] = False,
) -> None:
    """Store a secret. The value is never taken from the command line."""
    try:
        validate_secret_name(name)
    except ValueError as exc:
        fail(str(exc), code=EXIT_USAGE)
    paths = AppPaths.resolve()
    paths.ensure()
    value = read_secret_from_stdin() if stdin else prompt_new_secret(f"Value for {name}")
    store = SecretStore(paths)
    store.set(name, value)
    console.print(
        f"[green]Stored[/green] {escape(name)} "
        f"(protected by: {store.key_store.protector.description})."
    )


@secrets_app.command("list")
def secret_list() -> None:
    """List stored secret names. Values are never shown."""
    paths = AppPaths.resolve()
    entries = SecretStore(paths).describe()
    if not entries:
        console.print("No secrets are stored.")
        return
    table = Table("Name", "Last changed")
    for entry in entries:
        table.add_row(escape(str(entry["name"])), str(entry["updated_at"] or ""))
    console.print(table)


@secrets_app.command("delete")
def secret_delete(name: Annotated[str, typer.Argument(help="Secret name.")]) -> None:
    """Remove a stored secret."""
    try:
        validate_secret_name(name)
    except ValueError as exc:
        fail(str(exc), code=EXIT_USAGE)
    removed = SecretStore(AppPaths.resolve()).delete(name)
    console.print(f"Removed {escape(name)}." if removed else f"No secret named {escape(name)}.")


# --------------------------------------------------------------------------- config
@config_app.command("paths")
def config_paths() -> None:
    """Show where configuration, data and logs live."""
    paths = AppPaths.resolve()
    table = Table("Location", "Path", "Present")
    table.add_row("Data directory", str(paths.home), "yes" if paths.home.is_dir() else "no")
    table.add_row("Logs", str(paths.logs_dir), "yes" if paths.logs_dir.is_dir() else "no")
    table.add_row("Backups", str(paths.backups_dir), "yes" if paths.backups_dir.is_dir() else "no")
    root = project_root()
    table.add_row("Program directory", str(root) if root else "(installed package)", "yes")
    table.add_row("Default settings", str(default_config_dir()), "yes")
    for label, path, exists in config_files(paths):
        table.add_row(f"Config: {label}", str(path), "yes" if exists else "no")
    console.print(table)
    console.print("[dim]Priority: environment variables, .env files, user settings, defaults.[/dim]")


@config_app.command("validate")
def config_validate() -> None:
    """Check the configuration and report every problem found."""
    paths = AppPaths.resolve()
    try:
        load_settings(paths)
    except OmniError as exc:
        console.print(f"[red]Invalid.[/red] {escape(exc.message)}")
        if exc.hint:
            console.print(f"[dim]{escape(exc.hint)}[/dim]")
        raise typer.Exit(EXIT_CONFIGURATION) from exc
    console.print("[green]The configuration is valid.[/green]")


@config_app.command("show")
def config_show(
    json_output: Annotated[bool, typer.Option("--json", help="JSON instead of YAML.")] = False,
) -> None:
    """Print the effective configuration. Secrets are masked."""
    use_json(json_output)
    settings = load_settings(AppPaths.resolve())
    data = settings.public_dict()
    if json_output:
        emit_json(data)
    else:
        sys.stdout.write(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))


def known_roles() -> str:
    return ", ".join(sorted(BUILTIN_ROLE_NAMES))
