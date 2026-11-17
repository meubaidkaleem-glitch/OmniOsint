"""Health checks shared by the API, the CLI and the start-up sequence."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths, default_frontend_dist
from omniosint.core.timeutil import utcnow
from omniosint.database.engine import Database, describe_target
from omniosint.database.migrate import schema_state
from omniosint.system import registry

MIN_POSTGRES_VERSION = 140000
RECOMMENDED_POSTGRES_VERSION = 150000
LOW_DISK_BYTES = 1 * 1024**3
CRITICAL_DISK_BYTES = 200 * 1024**2
_CHECK_TIMEOUT_SECONDS = 8.0


class ComponentState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    label: str
    status: ComponentState
    required: bool
    detail: str
    latency_ms: float | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HealthReport:
    status: ComponentState
    checked_at: datetime
    components: list[ComponentHealth]

    @property
    def ready(self) -> bool:
        """Whether the application can serve requests (possibly degraded)."""
        return self.status in (ComponentState.OK, ComponentState.DEGRADED)

    def component(self, name: str) -> ComponentHealth | None:
        return next((item for item in self.components if item.name == name), None)


def describe_database_error(exc: BaseException) -> str:
    """A short, safe reason for a database failure (never includes credentials)."""
    name = type(exc).__name__
    text = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in name.lower():
        return "connection timed out"
    if "invalidpassword" in name.lower() or "password authentication failed" in text:
        return "authentication failed (check the database user and password)"
    if "invalidauthorizationspecification" in name.lower():
        return "authentication failed (check the database user and password)"
    if "invalidcatalogname" in name.lower() or ("does not exist" in text and "database" in text):
        return "the database does not exist"
    if isinstance(exc, ConnectionRefusedError) or "connection refused" in text:
        return "connection refused (is PostgreSQL running?)"
    if isinstance(exc, OSError):
        return "the server could not be reached"
    return f"connection failed ({name})"


async def check_database(db: Database) -> ComponentHealth:
    label = "PostgreSQL database"
    target = describe_target(db.url)
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            latency = await db.ping()
            version_number, version_label = await db.server_version()
            state = await schema_state(db.engine)
    except Exception as exc:
        return ComponentHealth(
            name="database",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=True,
            detail=f"Not reachable at {target}: {describe_database_error(exc)}.",
        )

    data = {
        "target": target,
        "server_version": version_label,
        "schema_revision": state.current,
        "schema_head": state.head,
    }
    if version_number < MIN_POSTGRES_VERSION:
        return ComponentHealth(
            name="database",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=True,
            detail=f"PostgreSQL {version_label} is too old; version 15 or later is required.",
            latency_ms=latency,
            data=data,
        )
    if not state.initialised:
        return ComponentHealth(
            name="database",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=True,
            detail="Connected, but the schema has not been created. Run: omniosint db upgrade",
            latency_ms=latency,
            data=data,
        )
    if not state.up_to_date:
        return ComponentHealth(
            name="database",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=True,
            detail=(
                f"Schema is at revision {state.current} but this version needs {state.head}. "
                "Run: omniosint db upgrade"
            ),
            latency_ms=latency,
            data=data,
        )
    return ComponentHealth(
        name="database",
        label=label,
        status=ComponentState.OK,
        required=True,
        detail=f"PostgreSQL {version_label}, schema revision {state.current}.",
        latency_ms=latency,
        data=data,
    )


async def check_redis(settings: Settings) -> ComponentHealth:
    label = "Redis cache"
    if settings.redis.url is None:
        return ComponentHealth(
            name="redis",
            label=label,
            status=ComponentState.NOT_CONFIGURED,
            required=False,
            detail="Not configured (optional). In-process fallbacks are in use.",
        )
    import redis.asyncio as redis_asyncio
    from redis.exceptions import RedisError

    timeout = settings.redis.socket_timeout_seconds
    client = redis_asyncio.Redis.from_url(
        settings.redis.url.get_secret_value(),
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
    )
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        async with asyncio.timeout(timeout + 1):
            await client.ping()
            info = await client.info("server")
    except (RedisError, OSError, TimeoutError, ValueError) as exc:
        return ComponentHealth(
            name="redis",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=False,
            detail=f"Configured but not reachable ({type(exc).__name__}).",
        )
    finally:
        await client.aclose()
    version = str(info.get("redis_version", "unknown"))
    return ComponentHealth(
        name="redis",
        label=label,
        status=ComponentState.OK,
        required=False,
        detail=f"Redis {version}.",
        latency_ms=(loop.time() - started) * 1000.0,
        data={"server_version": version},
    )


async def check_worker(db: Database, settings: Settings) -> ComponentHealth:
    label = "Background worker"
    allowed_silence = max(30.0, settings.worker.heartbeat_seconds * 3.0)
    try:
        async with asyncio.timeout(_CHECK_TIMEOUT_SECONDS):
            async with db.session() as session:
                instance = await registry.latest(session, "worker")
    except Exception:
        return ComponentHealth(
            name="worker",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=False,
            detail="Unknown: the database could not be queried.",
        )
    if instance is None:
        return ComponentHealth(
            name="worker",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=False,
            detail="No worker is running.",
        )
    silence = (utcnow() - instance.last_heartbeat_at).total_seconds()
    data = {
        "pid": instance.pid,
        "version": instance.version,
        "started_at": instance.started_at.isoformat(),
        "last_heartbeat_seconds_ago": round(silence, 1),
    }
    if silence > allowed_silence:
        return ComponentHealth(
            name="worker",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=False,
            detail=f"No heartbeat for {int(silence)} seconds.",
            data=data,
        )
    return ComponentHealth(
        name="worker",
        label=label,
        status=ComponentState.OK,
        required=False,
        detail=f"Running (process {instance.pid}).",
        data=data,
    )


def check_storage(paths: AppPaths) -> ComponentHealth:
    label = "Data directory"
    home = paths.home
    try:
        paths.ensure()
        probe = paths.run_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        free = shutil.disk_usage(home).free
    except OSError as exc:
        return ComponentHealth(
            name="storage",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=True,
            detail=f"{home} is not writable ({exc.strerror or type(exc).__name__}).",
        )
    free_gib = free / 1024**3
    data = {"path": str(home), "free_bytes": free}
    if free < CRITICAL_DISK_BYTES:
        status = ComponentState.UNAVAILABLE
        detail = f"Only {free / 1024**2:.0f} MiB free on the data volume."
    elif free < LOW_DISK_BYTES:
        status = ComponentState.DEGRADED
        detail = f"Low disk space: {free_gib:.2f} GiB free."
    else:
        status = ComponentState.OK
        detail = f"Writable, {free_gib:.1f} GiB free."
    return ComponentHealth(
        name="storage", label=label, status=status, required=True, detail=detail, data=data
    )


def frontend_dist_dir(settings: Settings) -> Path | None:
    return settings.server.frontend_dist or default_frontend_dist()


def check_web_interface(settings: Settings) -> ComponentHealth:
    label = "Web interface"
    if not settings.server.serve_frontend:
        return ComponentHealth(
            name="web_interface",
            label=label,
            status=ComponentState.NOT_CONFIGURED,
            required=False,
            detail="Serving the web interface is turned off (server.serve_frontend).",
        )
    dist = frontend_dist_dir(settings)
    if dist is None or not (dist / "index.html").is_file():
        return ComponentHealth(
            name="web_interface",
            label=label,
            status=ComponentState.UNAVAILABLE,
            required=False,
            detail="Not built. Run the installer, or `npm run build` in the frontend folder.",
            data={"path": str(dist) if dist else None},
        )
    return ComponentHealth(
        name="web_interface",
        label=label,
        status=ComponentState.OK,
        required=False,
        detail="Built and served by the API.",
        data={"path": str(dist)},
    )


def overall_status(components: list[ComponentHealth]) -> ComponentState:
    if any(
        item.required and item.status in (ComponentState.UNAVAILABLE, ComponentState.NOT_CONFIGURED)
        for item in components
    ):
        return ComponentState.UNAVAILABLE
    if any(
        item.status in (ComponentState.UNAVAILABLE, ComponentState.DEGRADED) for item in components
    ):
        return ComponentState.DEGRADED
    return ComponentState.OK


async def collect_health(
    db: Database, settings: Settings, paths: AppPaths, *, include_worker: bool = True
) -> HealthReport:
    """Run every check concurrently and summarise."""
    checks: list[Any] = [check_database(db), check_redis(settings)]
    if include_worker:
        checks.append(check_worker(db, settings))
    results: list[ComponentHealth] = list(await asyncio.gather(*checks))
    results.append(await asyncio.to_thread(check_storage, paths))
    results.append(check_web_interface(settings))
    return HealthReport(status=overall_status(results), checked_at=utcnow(), components=results)
