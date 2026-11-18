"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from omniosint import __version__
from omniosint.api.context import AppContext
from omniosint.api.errors import install_error_handlers
from omniosint.api.middleware import (
    BodySizeLimitMiddleware,
    HostValidationMiddleware,
    OriginGuardMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from omniosint.api.routers.v1 import (
    admin,
    auth,
    collection,
    dashboard,
    evidence,
    providers,
    scopes,
    search,
    system,
)
from omniosint.api.static import mount_frontend
from omniosint.collection.runtime import IntelRuntime
from omniosint.core.config import Settings, load_settings
from omniosint.core.logging import get_logger
from omniosint.core.paths import AppPaths
from omniosint.system.health import frontend_dist_dir
from omniosint.system.registry import ServiceHeartbeat

log = get_logger(__name__)

API_PREFIX = "/api/v1"
DOCS_PATH = "/api/docs"

OPENAPI_TAGS = [
    {
        "name": "auth",
        "description": "First-run setup, sign-in and the caller's own account.",
    },
    {
        "name": "admin",
        "description": "User accounts, roles and the audit trail.",
    },
    {
        "name": "system",
        "description": "Health, version, the feature registry and system status.",
    },
    {
        "name": "dashboard",
        "description": "Dashboard data. Every number is a database record.",
    },
    {
        "name": "providers",
        "description": (
            "The provider catalogue, the adapters that exist and their health checks. "
            "No real provider is integrated yet."
        ),
    },
]

DESCRIPTION = """\
OmniOSINT is an evidence-driven OSINT and intelligence investigation platform.

This API is versioned under `/api/v1`. It covers the platform foundation
(authentication, administration, health, the feature and provider registries)
and the core intelligence pipeline: universal search, collection plans,
requests and jobs, evidence, entities, sources and scopes. Endpoint groups for
investigations, graphs, monitoring, reports, AI and workflows are added by the
phase that implements them; they are not present as placeholders.

No real provider is integrated yet. Collection results from the simulated
provider, when it is enabled, are marked `is_simulated`.
"""


def _lifespan(context: AppContext):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        settings = context.settings
        log.info(
            "api.starting",
            version=__version__,
            environment=settings.environment,
            host=settings.server.host,
            port=settings.server.port,
        )
        try:
            async with context.db.session() as session:
                token = await context.auth.ensure_setup_token(session, context.paths)
            if token is not None:
                # The token itself is never logged, only where to find it.
                log.warning(
                    "setup.pending",
                    message="No user exists yet. Complete first-run setup.",
                    token_file=str(context.paths.setup_token_file),
                )
        except Exception as exc:
            log.error(
                "api.database_unavailable_at_startup",
                error=type(exc).__name__,
                hint="The API keeps running and reports not ready until the database is usable.",
            )

        try:
            context.intel = await IntelRuntime.build(settings, context.paths, context.db)
        except Exception as exc:
            log.error("api.collection_unavailable", error=type(exc).__name__)

        heartbeat = ServiceHeartbeat(context.db, "api", settings.worker.heartbeat_seconds)
        context.heartbeat = heartbeat
        await heartbeat.start()
        try:
            yield
        finally:
            await heartbeat.stop()
            if context.intel is not None:
                await context.intel.aclose()
                context.intel = None
            await context.db.dispose()
            log.info("api.stopped")

    return lifespan


def create_app(
    settings: Settings | None = None,
    *,
    paths: AppPaths | None = None,
    manage_lifespan: bool = True,
) -> FastAPI:
    """Build the application.

    ``manage_lifespan=False`` skips start-up work (database, heartbeat); it is
    used to produce the OpenAPI document without touching any service.
    """
    resolved_paths = paths or AppPaths.resolve()
    resolved_settings = settings or load_settings(resolved_paths)
    context = AppContext.build(resolved_settings, resolved_paths)

    docs_enabled = resolved_settings.docs_enabled
    app = FastAPI(
        title="OmniOSINT API",
        version=__version__,
        description=DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=DOCS_PATH if docs_enabled else None,
        redoc_url=None,
        openapi_tags=OPENAPI_TAGS,
        lifespan=_lifespan(context) if manage_lifespan else None,
    )
    app.state.ctx = context
    install_error_handlers(app)

    v1 = APIRouter(prefix=API_PREFIX)
    v1.include_router(auth.router)
    v1.include_router(admin.router)
    v1.include_router(system.router)
    v1.include_router(dashboard.router)
    v1.include_router(providers.router)
    v1.include_router(search.router)
    v1.include_router(collection.router)
    v1.include_router(evidence.router)
    v1.include_router(scopes.router)
    app.include_router(v1)

    if resolved_settings.server.serve_frontend:
        mount_frontend(app, frontend_dist_dir(resolved_settings))

    # add_middleware puts each new layer outside the previous one, so the list
    # below runs bottom-up: RequestContext is outermost.
    server = resolved_settings.server
    app.add_middleware(OriginGuardMiddleware, allowed_origins=server.cors_origins)
    if server.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(server.cors_origins),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
            expose_headers=["X-Request-ID"],
        )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=server.max_request_body_bytes)
    app.add_middleware(
        SecurityHeadersMiddleware,
        csp_exempt_prefixes=(DOCS_PATH,) if docs_enabled else (),
    )
    app.add_middleware(HostValidationMiddleware, allowed_hosts=server.allowed_hosts)
    app.add_middleware(RequestContextMiddleware, access_log=resolved_settings.logging.access_log)
    return app
