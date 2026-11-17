"""`omniosint db ...` - database connectivity and schema management."""

from __future__ import annotations

import secrets as secrets_module
import time
from typing import Annotated

import typer

from omniosint.cli.common import (
    EXIT_FAILURE,
    EXIT_UNAVAILABLE,
    Runtime,
    console,
    emit_json,
    escape,
    fail,
    load_runtime,
    open_database,
    read_secret_from_stdin,
    run_async,
    use_json,
)
from omniosint.core.secrets import DATABASE_PASSWORD, SecretStore
from omniosint.database import migrate
from omniosint.database.bootstrap import bootstrap_database
from omniosint.database.engine import build_database_url, describe_target
from omniosint.database.seeds import seed_builtin
from omniosint.system.health import ComponentHealth, ComponentState, check_database

app = typer.Typer(help="Database connectivity and schema.", no_args_is_help=True)


async def _check(runtime: Runtime) -> ComponentHealth:
    async with open_database(runtime) as database:
        return await check_database(database)


def _exit_code(result: ComponentHealth) -> int:
    if result.status is ComponentState.OK:
        return 0
    return EXIT_FAILURE if result.data.get("schema_head") else EXIT_UNAVAILABLE


@app.command("check")
def check(
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output.")] = False,
) -> None:
    """Verify that the database is reachable and its schema is current."""
    use_json(json_output)
    runtime = load_runtime()
    result = run_async(_check(runtime))
    if json_output:
        emit_json(
            {
                "ok": result.status is ComponentState.OK,
                "status": result.status.value,
                "detail": result.detail,
                "latency_ms": result.latency_ms,
                **result.data,
            }
        )
    else:
        colour = "green" if result.status is ComponentState.OK else "red"
        console.print(f"[{colour}]{result.status.value.upper()}[/{colour}] {escape(result.detail)}")
    raise typer.Exit(_exit_code(result))


@app.command("wait")
def wait(
    timeout: Annotated[int, typer.Option(help="Seconds to wait before giving up.")] = 60,
) -> None:
    """Wait until the database accepts connections (used by install scripts)."""
    runtime = load_runtime()
    deadline = time.monotonic() + timeout
    while True:
        result = run_async(_check(runtime))
        # A reachable server without a schema counts: the next step creates it.
        if result.status is ComponentState.OK or result.data.get("schema_head"):
            console.print(f"[green]Database reachable.[/green] {escape(result.detail)}")
            return
        if time.monotonic() >= deadline:
            fail(result.detail, code=EXIT_UNAVAILABLE)
        time.sleep(2)


@app.command("upgrade")
def upgrade() -> None:
    """Apply schema migrations and refresh built-in roles and permissions."""
    runtime = load_runtime()
    url = build_database_url(runtime.settings, runtime.paths)

    async def before() -> str | None:
        async with open_database(runtime) as database:
            await database.ping()
            return await migrate.current_revision(database.engine)

    previous = run_async(before())
    migrate.upgrade(url)

    async def after() -> tuple[str | None, int, int]:
        async with open_database(runtime) as database:
            async with database.session() as session:
                report = await seed_builtin(session)
                await session.commit()
            return await migrate.current_revision(database.engine), report.roles, report.permissions

    current, roles, permissions = run_async(after())
    if previous == current:
        console.print(f"[green]Schema already up to date[/green] (revision {current}).")
    else:
        console.print(
            f"[green]Schema upgraded[/green] from {previous or 'empty'} to revision {current}."
        )
    console.print(f"Built-in data refreshed: {roles} roles, {permissions} permissions.")


@app.command("current")
def current() -> None:
    """Show the schema revision of the database and the one this version needs."""
    runtime = load_runtime()

    async def read() -> migrate.SchemaState:
        async with open_database(runtime) as database:
            return await migrate.schema_state(database.engine)

    state = run_async(read())
    console.print(f"Database: {state.current or 'no schema'}")
    console.print(f"Required: {state.head}")
    console.print(escape(state.describe()))
    if not state.up_to_date:
        raise typer.Exit(EXIT_FAILURE)


@app.command("bootstrap")
def bootstrap(
    admin_user: Annotated[
        str, typer.Option(help="PostgreSQL user allowed to create roles and databases.")
    ] = "postgres",
    admin_database: Annotated[
        str, typer.Option(help="Database to connect to as the administrator.")
    ] = "postgres",
    admin_password_stdin: Annotated[
        bool,
        typer.Option("--admin-password-stdin", help="Read the administrator password from stdin."),
    ] = False,
    reset_password: Annotated[
        bool,
        typer.Option(help="Also set a new password if the application role already exists."),
    ] = False,
) -> None:
    """Create the application role and database on the configured server.

    Uses the host, port, user and database name from the settings. A new random
    password is generated for the application role and saved in the protected
    secret store; it is never printed.
    """
    runtime = load_runtime()
    database_settings = runtime.settings.database
    if database_settings.url is not None:
        fail(
            "database.url is set. `db bootstrap` works with the separate host, port, "
            "user and name settings; create the database by hand instead."
        )

    if admin_password_stdin:
        admin_password: str | None = read_secret_from_stdin()
    else:
        entered = typer.prompt(
            f"Password for PostgreSQL user {admin_user!r} (leave empty if none)",
            hide_input=True,
            default="",
            show_default=False,
        )
        admin_password = entered or None

    role_password = secrets_module.token_urlsafe(24)
    result = run_async(
        bootstrap_database(
            host=database_settings.host,
            port=database_settings.port,
            admin_user=admin_user,
            admin_password=admin_password,
            admin_database=admin_database,
            role=database_settings.user,
            role_password=role_password,
            database=database_settings.name,
            reset_password=reset_password,
            ssl_mode=database_settings.ssl_mode,
            connect_timeout=database_settings.connect_timeout_seconds,
        )
    )
    target = describe_target(build_database_url(runtime.settings))
    if result.role_password_set:
        SecretStore(runtime.paths).set(DATABASE_PASSWORD, role_password)
        console.print(
            f"Role {database_settings.user!r}: "
            f"{'created' if result.role_created else 'password reset'}; "
            "password saved in the secret store."
        )
    else:
        console.print(
            f"Role {database_settings.user!r} already exists and was left unchanged. "
            "If OmniOSINT does not know its password yet, run: "
            "omniosint secrets set database.password"
        )
    console.print(
        f"Database {database_settings.name!r}: "
        f"{'created' if result.database_created else 'already exists'} ({escape(target)})."
    )
    console.print("Next: omniosint db upgrade")
