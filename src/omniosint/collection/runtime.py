"""Builds the collection machinery the same way for the API, the worker and the CLI."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any

import structlog
from sqlalchemy import select

from omniosint.collection.planner import Planner
from omniosint.core.config import Settings
from omniosint.core.paths import AppPaths
from omniosint.core.secrets import SecretStore, SecretStoreError
from omniosint.database.engine import Database
from omniosint.database.models import Provider
from omniosint.evidence.objectstore import ObjectStore
from omniosint.net.http import SafeHttpClient
from omniosint.providers.catalog import load_catalogue
from omniosint.providers.manager import ProviderManager
from omniosint.providers.ratelimit import LocalRateLimiter, RateLimiter, RedisRateLimiter
from omniosint.providers.registry import ProviderRegistry

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class IntelRuntime:
    settings: Settings
    registry: ProviderRegistry
    manager: ProviderManager
    planner: Planner
    secrets: SecretStore
    paths: AppPaths
    _store: ObjectStore | None = None
    _redis: Any = None

    @property
    def store(self) -> ObjectStore:
        """The object store, opened (and its key created) on first use."""
        if self._store is None:
            self._store = ObjectStore.open(self.paths.objects_dir, self.secrets)
        return self._store

    @classmethod
    async def build(
        cls, settings: Settings, paths: AppPaths, database: Database | None = None
    ) -> IntelRuntime:
        secrets = SecretStore(paths)
        disabled: set[str] = set()
        priorities: dict[str, int] = {}
        if database is not None:
            try:
                async with database.session() as session:
                    for row in (await session.execute(select(Provider))).scalars():
                        priorities[row.id] = row.priority
                        if not row.enabled:
                            disabled.add(row.id)
            except Exception as error:  # the database may not be migrated yet
                log.warning("collection.provider_flags_unavailable", error=type(error).__name__)

        def has_secret(name: str) -> bool:
            try:
                return name in secrets.names()
            except SecretStoreError:
                return False

        def lookup(name: str) -> str | None:
            try:
                return secrets.get(name)
            except SecretStoreError:
                return None

        registry = ProviderRegistry(
            load_catalogue(),
            simulated_enabled=settings.collection.enable_simulated_provider,
            has_secret=has_secret,
            disabled_ids=disabled,
            priorities=priorities,
        )
        limiter: RateLimiter = LocalRateLimiter()
        redis_client = None
        if settings.redis.url is not None:
            from redis.asyncio import from_url

            redis_client = from_url(
                settings.redis.url.get_secret_value(),
                socket_timeout=settings.redis.socket_timeout_seconds,
                socket_connect_timeout=settings.redis.socket_timeout_seconds,
            )
            limiter = RedisRateLimiter(redis_client)
        collection = settings.collection
        manager = ProviderManager(
            registry,
            rate_limiter=limiter,
            credential_lookup=lookup,
            http_factory=partial(
                SafeHttpClient,
                timeout_seconds=collection.http_timeout_seconds,
                max_bytes=collection.http_max_response_bytes,
            ),
            rate_limit_max_wait=collection.rate_limit_max_wait_seconds,
        )
        return cls(
            settings=settings,
            registry=registry,
            manager=manager,
            planner=Planner(registry, collection),
            secrets=secrets,
            paths=paths,
            _redis=redis_client,
        )

    async def aclose(self) -> None:
        await self.manager.aclose()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
