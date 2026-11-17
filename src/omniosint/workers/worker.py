"""Background worker process.

In this phase the worker keeps a heartbeat and runs housekeeping. The collection
job runner, the monitoring scheduler and report rendering are added to the same
process in later phases.
"""

from __future__ import annotations

import asyncio
import os
import signal
from datetime import timedelta

from omniosint import __version__
from omniosint.core.config import Settings
from omniosint.core.logging import configure_logging, get_logger
from omniosint.core.paths import AppPaths
from omniosint.database.engine import Database
from omniosint.runtime.shutdown import RUN_ID_ENV, ShutdownWatcher
from omniosint.system import registry
from omniosint.system.registry import ServiceHeartbeat
from omniosint.workers import housekeeping

log = get_logger(__name__)

_TICK_SECONDS = 1.0


class Worker:
    def __init__(self, settings: Settings, paths: AppPaths, db: Database | None = None) -> None:
        self._settings = settings
        self._paths = paths
        self._db = db or Database.from_settings(
            settings, paths, application_name="omniosint-worker"
        )
        self._owns_db = db is None
        self.heartbeat = ServiceHeartbeat(self._db, "worker", settings.worker.heartbeat_seconds)

    async def run_housekeeping(self) -> dict[str, int]:
        """Run every maintenance task once. Failures are logged, not raised."""
        results: dict[str, int] = {}
        worker_settings = self._settings.worker
        try:
            async with self._db.session() as session:
                results["sessions_purged"] = await housekeeping.purge_sessions(
                    session, worker_settings.session_retention_days
                )
            async with self._db.session() as session:
                results["instances_reaped"] = await registry.reap_stale(
                    session, timedelta(seconds=max(60, worker_settings.heartbeat_seconds * 4))
                )
        except Exception as exc:
            log.warning("housekeeping.failed", error=type(exc).__name__)
        else:
            log.info("housekeeping.completed", **results)
        return results

    async def run(self, stop: asyncio.Event) -> None:
        """Run until ``stop`` is set."""
        log.info("worker.starting", version=__version__, pid=os.getpid())
        await self.heartbeat.start()
        loop = asyncio.get_running_loop()
        next_housekeeping = loop.time()
        try:
            while not stop.is_set():
                if loop.time() >= next_housekeeping:
                    await self.run_housekeeping()
                    next_housekeeping = (
                        loop.time() + self._settings.worker.housekeeping_interval_seconds
                    )
                try:
                    await asyncio.wait_for(stop.wait(), timeout=_TICK_SECONDS)
                except TimeoutError:
                    continue
        finally:
            await self.heartbeat.stop()
            if self._owns_db:
                await self._db.dispose()
            log.info("worker.stopped")


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    def request_stop(*_args: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, request_stop)
        except (ValueError, OSError):  # not the main thread, or unsupported here
            pass


def run_worker(settings: Settings, paths: AppPaths) -> None:
    """Entry point of ``omniosint worker``."""
    configure_logging(settings.logging, service="worker", logs_dir=paths.logs_dir)

    async def main() -> None:
        stop = asyncio.Event()
        _install_signal_handlers(asyncio.get_running_loop(), stop)
        watcher = ShutdownWatcher(paths.run_dir, os.environ.get(RUN_ID_ENV), stop.set)
        watcher.start()
        try:
            await Worker(settings, paths).run(stop)
        finally:
            await watcher.stop()

    asyncio.run(main())
