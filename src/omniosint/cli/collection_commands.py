"""`omniosint classify | search | investigate | jobs | evidence | scopes`.

The CLI uses the same services as the API, with the actor "cli" in the audit
trail. `investigate` queues jobs for the background worker; `--run-here` runs
them in this process instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.table import Table

from omniosint.audit.service import CLI_ACTOR
from omniosint.cli.common import (
    EXIT_FAILURE,
    EXIT_USAGE,
    Runtime,
    console,
    emit_json,
    escape,
    fail,
    load_runtime,
    open_database,
    run_async,
    use_json,
)
from omniosint.collection import service as collection
from omniosint.collection.executor import Collector
from omniosint.collection.inputs import resolve
from omniosint.collection.planner import CollectionPlan, PlanOptions
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database.engine import Database
from omniosint.evidence import service as evidence_service
from omniosint.indicators import IndicatorType, classify, classify_file
from omniosint.indicators.files import HEAD_BYTES
from omniosint.indicators.model import Classification
from omniosint.scopes import service as scopes
from omniosint.system.health import ComponentState, check_worker

JsonOption = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]
TypeOption = Annotated[
    IndicatorType | None,
    typer.Option("--type", help="The reading to use when the input is ambiguous."),
]
ProviderOption = Annotated[
    list[str] | None, typer.Option("--provider", help="Use only this provider (repeatable).")
]
ModeOption = Annotated[str, typer.Option("--mode", help="passive (default) or active.")]
ScopeOption = Annotated[
    str | None, typer.Option("--scope", help="Scope id; needed for active operations.")
]
PaidOption = Annotated[
    bool, typer.Option("--include-paid", help="Also plan paid providers (they need approval).")
]

STATUS_COLOURS = {
    "ready": "green",
    "cached": "cyan",
    "needs_approval": "yellow",
    "blocked": "red",
    "skipped": "dim",
    "unavailable": "dim",
    "planned": "dim",
    "excluded": "dim",
    "succeeded": "green",
    "failed": "red",
    "cancelled": "dim",
    "queued": "cyan",
    "running": "cyan",
    "awaiting_approval": "yellow",
}


def _colour(status: str) -> str:
    colour = STATUS_COLOURS.get(status, "white")
    return f"[{colour}]{status.replace('_', ' ')}[/{colour}]"


def _uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        fail(f"{value!r} is not a valid {what} id.", code=EXIT_USAGE)


def _options(
    mode: str,
    scope: str | None,
    providers: list[str] | None,
    include_paid: bool,
    force_refresh: bool = False,
    extra: list[str] | None = None,
) -> PlanOptions:
    if mode not in ("passive", "active"):
        fail("--mode must be passive or active.", code=EXIT_USAGE)
    provider_options: dict[str, Any] = {}
    for item in extra or []:
        key, separator, value = item.partition("=")
        if not separator or not key:
            fail(f"--option {item!r}: write key=value.", code=EXIT_USAGE)
        provider_options[key] = int(value) if value.isdigit() else value
    return PlanOptions(
        mode=mode,  # type: ignore[arg-type]
        strategy="include_paid" if include_paid else "free_first",
        providers=tuple(providers) if providers else None,
        scope_id=_uuid(scope, "scope") if scope else None,
        force_refresh=force_refresh,
        provider_options=provider_options,
    )


# --------------------------------------------------------------------------- output
def print_classification(result: Classification) -> None:
    console.print(escape(result.message))
    if not result.candidates:
        for hint in result.hints:
            console.print(f"[dim]{escape(hint)}[/dim]")
        return
    table = Table("Type", "Value", "Rank", "Reason")
    for item in result.candidates:
        table.add_row(item.type.value, escape(item.display), item.rank, escape(item.reason))
    console.print(table)
    notes = dict.fromkeys(note for item in result.candidates for note in item.notes)
    for note in notes:
        console.print(f"[dim]- {escape(note)}[/dim]")
    if result.mentions:
        console.print("Mentioned indicators:")
        for item in result.mentions:
            console.print(f"  {item.type.value}: {escape(item.display)}")


def print_plan(plan: CollectionPlan) -> None:
    data = plan.as_dict()
    indicator = data["indicator"]
    console.print(
        f"Plan for {indicator['label'].lower()} [bold]{escape(indicator['display'])}[/bold] "
        f"({data['mode']} mode)"
    )
    table = Table("Provider", "Capability", "Status", "Reason")
    for step in plan.steps:
        table.add_row(
            escape(step.provider_name),
            escape(step.capability_name or "-"),
            _colour(step.status),
            escape(step.message) + (f" (Phase {step.phase})" if step.phase else ""),
        )
    console.print(table)
    for warning in plan.warnings:
        console.print(f"[yellow]{escape(warning)}[/yellow]")


# --------------------------------------------------------------------------- classify
def register(app: typer.Typer) -> None:
    app.command("classify")(classify_command)
    app.command("search")(search_command)
    app.command("investigate")(investigate_command)
    app.add_typer(jobs_app, name="jobs")
    app.add_typer(evidence_app, name="evidence")
    app.add_typer(scopes_app, name="scopes")


def classify_command(
    input_value: Annotated[
        str | None, typer.Argument(metavar="INPUT", help="What to classify.")
    ] = None,
    file: Annotated[
        Path | None,
        typer.Option("--file", help="Classify a file from its first bytes (nothing is opened)."),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Classify an input: which of the 24 types it is, validated and normalised."""
    use_json(json_output)
    runtime = load_runtime()
    if (input_value is None) == (file is None):
        fail("Give either INPUT or --file.", code=EXIT_USAGE)
    if file is not None:
        if not file.is_file():
            fail(f"{file} is not a file.", code=EXIT_USAGE)
        digest = hashlib.sha256()
        with file.open("rb") as handle:
            head = handle.read(HEAD_BYTES)
            digest.update(head)
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        result = classify_file(file.name, head, file.stat().st_size, digest.hexdigest())
    else:
        assert input_value is not None
        result = classify(
            input_value, default_region=runtime.settings.collection.default_phone_region
        )
    if json_output:
        emit_json({"ok": True, "classification": result.model_dump(mode="json")})
        return
    print_classification(result)


# --------------------------------------------------------------------------- search and investigate
async def _with_intel(runtime: Runtime, work: Any) -> Any:
    async with open_database(runtime) as database:
        intel = await IntelRuntime.build(runtime.settings, runtime.paths, database)
        try:
            return await work(database, intel)
        finally:
            await intel.aclose()


def search_command(
    input_value: Annotated[str, typer.Argument(metavar="INPUT", help="Indicator to look up.")],
    indicator_type: TypeOption = None,
    mode: ModeOption = "passive",
    scope: ScopeOption = None,
    provider: ProviderOption = None,
    include_paid: PaidOption = False,
    json_output: JsonOption = False,
) -> None:
    """Classify an input and preview its collection plan. Nothing is collected."""
    use_json(json_output)
    runtime = load_runtime()
    indicator, result = resolve(
        input_value, indicator_type, default_region=runtime.settings.collection.default_phone_region
    )
    options = _options(mode, scope, provider, include_paid)

    async def work(database: Database, intel: IntelRuntime) -> CollectionPlan:
        async with database.session() as session:
            return await collection.preview(session, intel, indicator, options)

    plan = run_async(_with_intel(runtime, work))
    if json_output:
        emit_json(
            {"ok": True, "classification": result.model_dump(mode="json"), "plan": plan.as_dict()}
        )
        return
    print_plan(plan)


def investigate_command(
    input_value: Annotated[str, typer.Argument(metavar="INPUT", help="Indicator to investigate.")],
    indicator_type: TypeOption = None,
    mode: ModeOption = "passive",
    scope: ScopeOption = None,
    provider: ProviderOption = None,
    include_paid: PaidOption = False,
    force_refresh: Annotated[
        bool, typer.Option("--force-refresh", help="Ignore fresh cached results.")
    ] = False,
    option: Annotated[
        list[str] | None,
        typer.Option("--option", help="key=value for the simulated provider (repeatable)."),
    ] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show the plan only.")] = False,
    wait: Annotated[
        bool, typer.Option("--wait/--no-wait", help="Wait for the jobs to finish.")
    ] = True,
    run_here: Annotated[
        bool, typer.Option("--run-here", help="Run the jobs in this process, not in the worker.")
    ] = False,
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the jobs.")] = 300.0,
    json_output: JsonOption = False,
) -> None:
    """Plan and run collection for an indicator, then show the results.

    Active operations and paid calls wait for approval (`omniosint jobs approve`).
    """
    use_json(json_output)
    runtime = load_runtime()
    indicator, result = resolve(
        input_value, indicator_type, default_region=runtime.settings.collection.default_phone_region
    )
    options = _options(mode, scope, provider, include_paid, force_refresh, option)
    if dry_run:

        async def preview(database: Database, intel: IntelRuntime) -> CollectionPlan:
            async with database.session() as session:
                return await collection.preview(session, intel, indicator, options)

        plan = run_async(_with_intel(runtime, preview))
        if json_output:
            emit_json({"ok": True, "plan": plan.as_dict()})
        else:
            print_plan(plan)
        return

    async def work(database: Database, intel: IntelRuntime) -> dict[str, Any]:
        async with database.session() as session:
            request = await collection.submit(
                session,
                intel,
                indicator=indicator,
                input_text=result.input,
                options=options,
                actor=CLI_ACTOR,
            )
        request_id = request.id
        note = None
        if wait:
            if run_here:
                collector = Collector(database, runtime.settings, intel.manager, intel.store)
                await _settle(database, request_id, timeout, collector)
            elif (await check_worker(database, runtime.settings)).status is ComponentState.OK:
                await _settle(database, request_id, timeout, None)
            else:
                note = (
                    "The background worker is not running: the jobs are queued and will run "
                    "when OmniOSINT is started. Use --run-here to run them now."
                )
        return await _summary(database, request_id, note)

    summary = run_async(_with_intel(runtime, work))
    if json_output:
        emit_json({"ok": True, **summary})
    else:
        _print_summary(summary)
    if any(job["status"] == "failed" for job in summary["jobs"]):
        raise typer.Exit(EXIT_FAILURE)


async def _settle(
    database: Database, request_id: uuid.UUID, wait_seconds: float, collector: Collector | None
) -> None:
    deadline = asyncio.get_running_loop().time() + wait_seconds
    while asyncio.get_running_loop().time() < deadline:
        if collector is not None:
            await collector.drain()
        async with database.session() as session:
            detail = await collection.get_request(session, request_id)
        if all(job.status not in ("queued", "running") for job in detail.jobs):
            return
        await asyncio.sleep(0.5)


async def _summary(database: Database, request_id: uuid.UUID, note: str | None) -> dict[str, Any]:
    async with database.session() as session:
        detail = await collection.get_request(session, request_id)
        jobs = []
        for job in detail.jobs:
            evidence = await evidence_service.list_evidence(session, job_id=job.id, limit=50)
            jobs.append(
                {
                    "id": str(job.id),
                    "provider": job.provider_id,
                    "capability": job.capability,
                    "status": job.status,
                    "simulated": job.is_simulated,
                    "error": job.error,
                    "outcome": job.outcome,
                    "evidence": [
                        {
                            "id": str(item.id),
                            "kind": item.observation_kind,
                            "attributes": item.normalized.get("attributes"),
                            "related": item.normalized.get("related"),
                            "simulated": item.is_simulated,
                        }
                        for item in evidence.items
                    ],
                }
            )
    return {
        "request": {
            "id": str(detail.request.id),
            "status": detail.request.status,
            "indicator_type": detail.request.indicator_type,
            "indicator": detail.request.indicator_value,
            "simulated": detail.request.is_simulated,
        },
        "jobs": jobs,
        "note": note,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    request = summary["request"]
    console.print(
        f"Request {request['id']}: {_colour(request['status'])} "
        f"for {request['indicator_type']} {escape(request['indicator'])}"
    )
    if request["simulated"]:
        console.print("[yellow]Simulated data: nothing below describes anything real.[/yellow]")
    for job in summary["jobs"]:
        console.print(
            f"  {escape(job['provider'])} / {escape(job['capability'])}: {_colour(job['status'])}"
        )
        if job["error"]:
            console.print(f"    [red]{escape(job['error'].get('message', ''))}[/red]")
        for item in job["evidence"]:
            related = ", ".join(entry.get("value", "") for entry in item.get("related") or [])
            console.print(
                f"    - {escape(item['kind'])}" + (f": {escape(related)}" if related else "")
            )
    if summary.get("note"):
        console.print(f"[yellow]{escape(summary['note'])}[/yellow]")


# --------------------------------------------------------------------------- jobs
jobs_app = typer.Typer(
    help="Collection jobs: history, approval, cancellation, retry.", no_args_is_help=True
)


@jobs_app.command("list")
def jobs_list(
    status: Annotated[str | None, typer.Option(help="Only jobs in this state.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
    json_output: JsonOption = False,
) -> None:
    """List jobs, newest first."""
    use_json(json_output)
    runtime = load_runtime()

    async def work() -> list[Any]:
        async with open_database(runtime) as database, database.session() as session:
            return (await collection.list_jobs(session, status=status, limit=limit)).items

    jobs = run_async(work())
    if json_output:
        emit_json({"ok": True, "jobs": [_job_dict(job) for job in jobs]})
        return
    table = Table("Job", "Indicator", "Provider", "Capability", "Status", "Attempt", "Created")
    for job in jobs:
        table.add_row(
            str(job.id),
            escape(job.indicator_value),
            job.provider_id,
            job.capability,
            _colour(job.status),
            f"{job.attempt}/{job.max_attempts}",
            isoformat(job.created_at) or "",
        )
    console.print(table)


def _job_dict(job: Any) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "request_id": str(job.request_id),
        "indicator_type": job.indicator_type,
        "indicator": job.indicator_value,
        "provider": job.provider_id,
        "capability": job.capability,
        "status": job.status,
        "active": job.is_active,
        "simulated": job.is_simulated,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "outcome": job.outcome,
        "created_at": isoformat(job.created_at),
    }


@jobs_app.command("show")
def jobs_show(job_id: str, json_output: JsonOption = False) -> None:
    """Show a job and its history."""
    use_json(json_output)
    runtime = load_runtime()
    identifier = _uuid(job_id, "job")

    async def work() -> Any:
        async with open_database(runtime) as database, database.session() as session:
            return await collection.get_job(session, identifier)

    detail = run_async(work())
    events = [
        {"at": isoformat(event.occurred_at), "kind": event.kind, "message": event.message}
        for event in detail.events
    ]
    if json_output:
        emit_json(
            {
                "ok": True,
                "job": _job_dict(detail.job),
                "events": events,
                "evidence": detail.evidence_count,
            }
        )
        return
    job = detail.job
    console.print(f"Job {job.id}: {_colour(job.status)} ({job.provider_id} / {job.capability})")
    for event in events:
        console.print(f"  {event['at']}  {event['kind']:<16} {escape(event['message'])}")
    console.print(f"Evidence records: {detail.evidence_count}")


def _job_action(name: str, job_id: str, json_output: bool) -> None:
    use_json(json_output)
    runtime = load_runtime()
    identifier = _uuid(job_id, "job")
    action = {
        "approve": collection.approve_job,
        "cancel": collection.cancel_job,
        "retry": collection.retry_job,
    }[name]

    async def work() -> Any:
        async with open_database(runtime) as database, database.session() as session:
            return await action(session, identifier, actor=CLI_ACTOR)

    job = run_async(work())
    if json_output:
        emit_json({"ok": True, "job": _job_dict(job)})
    else:
        console.print(f"Job {job.id}: {_colour(job.status)}")


@jobs_app.command("approve")
def jobs_approve(job_id: str, json_output: JsonOption = False) -> None:
    """Approve a job that waits for approval (active operations, paid calls)."""
    _job_action("approve", job_id, json_output)


@jobs_app.command("cancel")
def jobs_cancel(job_id: str, json_output: JsonOption = False) -> None:
    """Cancel a job."""
    _job_action("cancel", job_id, json_output)


@jobs_app.command("retry")
def jobs_retry(job_id: str, json_output: JsonOption = False) -> None:
    """Retry a failed or cancelled job."""
    _job_action("retry", job_id, json_output)


# --------------------------------------------------------------------------- evidence
evidence_app = typer.Typer(help="Evidence collected by jobs.", no_args_is_help=True)


@evidence_app.command("list")
def evidence_list(
    job: Annotated[str | None, typer.Option(help="Only evidence from this job.")] = None,
    entity: Annotated[str | None, typer.Option(help="Only evidence about this entity.")] = None,
    limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
    json_output: JsonOption = False,
) -> None:
    """List evidence, newest first."""
    use_json(json_output)
    runtime = load_runtime()

    async def work() -> list[Any]:
        async with open_database(runtime) as database, database.session() as session:
            page = await evidence_service.list_evidence(
                session,
                job_id=_uuid(job, "job") if job else None,
                entity_id=_uuid(entity, "entity") if entity else None,
                limit=limit,
            )
            return page.items

    items = run_async(work())
    if json_output:
        emit_json({"ok": True, "evidence": [_evidence_dict(item) for item in items]})
        return
    table = Table("Evidence", "Kind", "Source", "Collected", "Simulated")
    for item in items:
        table.add_row(
            str(item.id),
            escape(item.observation_kind),
            item.source_id,
            isoformat(item.collected_at) or "",
            "yes" if item.is_simulated else "no",
        )
    console.print(table)


def _evidence_dict(item: Any) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "entity_id": str(item.entity_id),
        "kind": item.observation_kind,
        "source": item.source_id,
        "collected_at": isoformat(item.collected_at),
        "normalized": item.normalized,
        "raw_sha256": item.raw_sha256,
        "content_hash": item.content_hash,
        "simulated": item.is_simulated,
    }


@evidence_app.command("show")
def evidence_show(
    evidence_id: str,
    raw: Annotated[bool, typer.Option("--raw", help="Also show the raw response, masked.")] = False,
    json_output: JsonOption = False,
) -> None:
    """Show evidence with its integrity check."""
    use_json(json_output)
    runtime = load_runtime()
    identifier = _uuid(evidence_id, "evidence")

    async def work(database: Database, intel: IntelRuntime) -> dict[str, Any]:
        async with database.session() as session:
            item = await evidence_service.get_evidence(session, identifier)
            integrity = await evidence_service.check_integrity(session, item, intel.store)
            body: Any = None
            if raw and item.raw_sha256 and integrity.raw_available:
                body = evidence_service.raw_view(
                    intel.store.get(item.raw_sha256), "application/json", redacted=True
                )
            return {"evidence": _evidence_dict(item), "integrity": asdict(integrity), "raw": body}

    data = run_async(_with_intel(runtime, work))
    if json_output:
        emit_json({"ok": True, **data})
        return
    console.print_json(json.dumps(data, default=str))


# --------------------------------------------------------------------------- scopes
scopes_app = typer.Typer(
    help="Scopes: written authorisation for active operations.", no_args_is_help=True
)


@scopes_app.command("list")
def scopes_list(json_output: JsonOption = False) -> None:
    """List scopes."""
    use_json(json_output)
    runtime = load_runtime()

    async def work() -> list[Any]:
        async with open_database(runtime) as database, database.session() as session:
            return list(await scopes.list_scopes(session))

    items = run_async(work())
    rows = [
        {
            "id": str(item.id),
            "name": item.name,
            "mode": item.mode,
            "status": scopes.scope_status(item),
            "authorized_by": item.authorized_by,
            "valid_until": isoformat(item.valid_until),
        }
        for item in items
    ]
    if json_output:
        emit_json({"ok": True, "scopes": rows})
        return
    table = Table("Scope", "Name", "Mode", "Status", "Authorised by", "Valid until")
    for row in rows:
        table.add_row(
            row["id"],
            escape(row["name"]),
            row["mode"],
            row["status"],
            escape(row["authorized_by"]),
            row["valid_until"] or "",
        )
    console.print(table)


def _rule_input(text: str, *, exclusion: bool) -> scopes.RuleInput:
    kind, separator, value = text.partition("=")
    if not separator:
        fail(f"{text!r}: write kind=value, for example cidr=198.51.100.0/24.", code=EXIT_USAGE)
    return scopes.RuleInput(kind=kind.strip(), value=value.strip(), is_exclusion=exclusion)


@scopes_app.command("create")
def scopes_create(
    name: Annotated[str, typer.Option(help="A name for the engagement.")],
    authorized_by: Annotated[str, typer.Option(help="Who gave the written authorisation.")],
    rule: Annotated[
        list[str],
        typer.Option(
            "--rule", help="kind=value target (repeatable): domain, wildcard, ip, cidr, url_prefix."
        ),
    ],
    confirm_authorization: Annotated[
        bool,
        typer.Option(
            "--confirm-authorization",
            help="State that written authorisation exists for every target listed.",
        ),
    ] = False,
    mode: Annotated[
        str, typer.Option(help="authorized_discovery or active_assessment.")
    ] = "authorized_discovery",
    exclude: Annotated[
        list[str] | None, typer.Option("--exclude", help="kind=value exclusion (repeatable).")
    ] = None,
    valid_days: Annotated[
        int, typer.Option(min=1, max=366, help="Days the scope stays valid.")
    ] = 30,
    reference: Annotated[
        str | None, typer.Option(help="Authorisation reference (contract, ticket).")
    ] = None,
    json_output: JsonOption = False,
) -> None:
    """Record a scope of written authorisation."""
    use_json(json_output)
    runtime = load_runtime()
    rules = tuple(_rule_input(item, exclusion=False) for item in rule) + tuple(
        _rule_input(item, exclusion=True) for item in exclude or []
    )

    async def work() -> Any:
        async with open_database(runtime) as database, database.session() as session:
            return await scopes.create_scope(
                session,
                scopes.ScopeInput(
                    name=name,
                    mode=mode,
                    authorized_by=authorized_by,
                    valid_until=utcnow() + timedelta(days=valid_days),
                    authorization_confirmed=confirm_authorization,
                    authorization_reference=reference,
                    rules=rules,
                ),
                actor=CLI_ACTOR,
            )

    scope = run_async(work())
    if json_output:
        emit_json({"ok": True, "scope": {"id": str(scope.id), "name": scope.name}})
    else:
        console.print(f"[green]Created[/green] scope {scope.id} ({escape(scope.name)}).")


@scopes_app.command("revoke")
def scopes_revoke(
    scope_id: str,
    reason: Annotated[str, typer.Option(help="Why the scope is revoked.")],
    json_output: JsonOption = False,
) -> None:
    """Revoke a scope."""
    use_json(json_output)
    runtime = load_runtime()
    identifier = _uuid(scope_id, "scope")

    async def work() -> Any:
        async with open_database(runtime) as database, database.session() as session:
            return await scopes.revoke_scope(session, identifier, reason, actor=CLI_ACTOR)

    scope = run_async(work())
    if json_output:
        emit_json({"ok": True, "scope": {"id": str(scope.id), "status": "revoked"}})
    else:
        console.print(f"Scope {scope.id} revoked.")
