"""Runs the API under uvicorn."""

from __future__ import annotations

import asyncio
import os

import uvicorn

from omniosint.api.app import create_app
from omniosint.core.config import Settings, load_settings
from omniosint.core.logging import configure_logging
from omniosint.core.paths import AppPaths
from omniosint.runtime.shutdown import RUN_ID_ENV, ShutdownWatcher


def create_app_from_environment():  # type: ignore[no-untyped-def]
    """Application factory for ``uvicorn --factory`` (development reload mode)."""
    paths = AppPaths.resolve()
    settings = load_settings(paths)
    configure_logging(settings.logging, service="api", logs_dir=paths.logs_dir)
    return create_app(settings, paths=paths)


def run_api(settings: Settings, paths: AppPaths, *, reload: bool = False) -> None:
    """Entry point of ``omniosint serve``. Blocks until the server stops."""
    server_settings = settings.server
    if reload:
        uvicorn.run(
            "omniosint.runtime.server:create_app_from_environment",
            factory=True,
            host=server_settings.host,
            port=server_settings.port,
            reload=True,
            log_config=None,
            access_log=False,
            server_header=False,
        )
        return

    configure_logging(settings.logging, service="api", logs_dir=paths.logs_dir)
    app = create_app(settings, paths=paths)
    config = uvicorn.Config(
        app,
        host=server_settings.host,
        port=server_settings.port,
        log_config=None,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=max(1, settings.runtime.shutdown_timeout_seconds - 5),
    )
    server = uvicorn.Server(config)

    def request_exit() -> None:
        server.should_exit = True

    async def main() -> None:
        watcher = ShutdownWatcher(paths.run_dir, os.environ.get(RUN_ID_ENV), request_exit)
        watcher.start()
        try:
            await server.serve()
        finally:
            await watcher.stop()

    asyncio.run(main())
