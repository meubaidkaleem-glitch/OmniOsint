"""Layered application settings.

Sources, highest priority first:

1. explicit overrides passed to :func:`load_settings`
2. environment variables, e.g. ``OMNIOSINT_SERVER__PORT=9000``
3. ``.env`` in the project directory, then ``.env`` in the data directory
4. user settings: ``<data dir>/config/settings.yaml``
5. shipped defaults: ``config/settings.yaml`` and ``config/logging.yaml``

Unknown keys are rejected so that a typo is an error, not a silently ignored
setting. Secrets are never read from YAML.
"""

from __future__ import annotations

import ipaddress
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from omniosint.core.errors import ConfigurationError
from omniosint.core.paths import AppPaths, default_config_dir, project_root

ENV_PREFIX = "OMNIOSINT_"

# Keys that must not be supplied through YAML files: they are secrets and
# belong in the environment or the protected secret store.
SECRET_YAML_PATHS: tuple[tuple[str, str], ...] = (
    ("database", "password"),
    ("database", "url"),
    ("redis", "url"),
)

_yaml_layer: ContextVar[dict[str, Any] | None] = ContextVar("omniosint_yaml_layer", default=None)


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def is_loopback_host(host: str) -> bool:
    """True when ``host`` can only be reached from this machine."""
    candidate = host.strip().strip("[]").lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


class ServerSettings(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1024, le=65535)
    allow_non_loopback: bool = False
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1")
    cors_origins: tuple[str, ...] = ()
    serve_frontend: bool = True
    frontend_dist: Path | None = None
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    docs_enabled: bool | None = None

    @model_validator(mode="after")
    def _loopback_only_by_default(self) -> ServerSettings:
        if not is_loopback_host(self.host) and not self.allow_non_loopback:
            raise ValueError(
                f"server.host is {self.host!r}, which is reachable from other machines. "
                "OmniOSINT listens on the loopback interface only by default. Set "
                "server.allow_non_loopback to true to override (not recommended)."
            )
        return self

    @property
    def base_url(self) -> str:
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if host in ("0.0.0.0", "[::]"):  # noqa: S104 - translating a wildcard bind
            host = "127.0.0.1"
        return f"http://{host}:{self.port}"


class DatabaseSettings(_Section):
    url: SecretStr | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=5432, ge=1, le=65535)
    name: str = "omniosint"
    user: str = "omniosint"
    password: SecretStr | None = None
    ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = (
        "prefer"
    )
    pool_size: int = Field(default=5, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout_seconds: float = Field(default=10.0, gt=0)
    connect_timeout_seconds: float = Field(default=5.0, gt=0)
    statement_timeout_ms: int = Field(default=30_000, ge=0)
    pg_bin_dir: Path | None = None


class RedisSettings(_Section):
    url: SecretStr | None = None
    socket_timeout_seconds: float = Field(default=2.0, gt=0)


class AuthSettings(_Section):
    session_cookie_name: str = "omniosint_session"
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    session_idle_minutes: int = Field(default=120, ge=5, le=10_080)
    cookie_secure: bool = False
    password_min_length: int = Field(default=12, ge=8, le=128)
    max_failed_logins: int = Field(default=5, ge=3, le=50)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    login_rate_limit_per_minute: int = Field(default=10, ge=1, le=600)
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_kib: int = Field(default=65_536, ge=8_192)
    argon2_parallelism: int = Field(default=4, ge=1, le=16)


class LoggingSettings(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    console_format: Literal["auto", "console", "json"] = "auto"
    file_enabled: bool = True
    file_max_bytes: int = Field(default=10_485_760, ge=65_536)
    file_backup_count: int = Field(default=5, ge=0, le=100)
    access_log: bool = True


class WorkerSettings(_Section):
    heartbeat_seconds: int = Field(default=15, ge=1, le=300)
    housekeeping_interval_seconds: int = Field(default=300, ge=5)
    session_retention_days: int = Field(default=7, ge=0, le=3650)


class RuntimeSettings(_Section):
    startup_timeout_seconds: int = Field(default=60, ge=5, le=600)
    shutdown_timeout_seconds: int = Field(default=30, ge=1, le=600)


class CollectionSettings(_Section):
    # The simulated provider generates labelled test data; never enable it for real work.
    enable_simulated_provider: bool = False
    # ISO 3166 region assumed for phone numbers written without a country code.
    default_phone_region: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    raw_retention_days: int = Field(default=90, ge=1, le=3650)
    max_concurrent_jobs: int = Field(default=4, ge=1, le=32)
    job_lease_seconds: int = Field(default=120, ge=30, le=3600)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_base_seconds: float = Field(default=5.0, ge=0.1, le=300)
    retry_max_seconds: float = Field(default=300.0, ge=0.1, le=3600)
    # Paid calls estimated above this many credits wait for approval (0: every paid call).
    approval_credit_threshold: float = Field(default=0.0, ge=0)
    rate_limit_max_wait_seconds: float = Field(default=30.0, ge=0, le=600)
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    http_max_response_bytes: int = Field(default=10_485_760, ge=1024, le=104_857_600)
    poll_interval_seconds: float = Field(default=1.0, ge=0.05, le=60)


class _MappingSource(PydanticBaseSettingsSource):
    """Feeds an already-loaded mapping into the settings pipeline."""

    def __init__(self, settings_cls: type[BaseSettings], data: dict[str, Any]) -> None:
        super().__init__(settings_cls)
        self._data = data

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        extra="ignore",
        frozen=True,
    )

    environment: Literal["production", "development", "test"] = "production"
    server: ServerSettings = Field(default_factory=ServerSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    collection: CollectionSettings = Field(default_factory=CollectionSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        layer = _yaml_layer.get()
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        if layer:
            sources.append(_MappingSource(settings_cls, layer))
        return tuple(sources)

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def docs_enabled(self) -> bool:
        if self.server.docs_enabled is not None:
            return self.server.docs_enabled
        return self.is_development

    def public_dict(self) -> dict[str, Any]:
        """Settings with every secret masked, safe to print or log."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# YAML layers
# ---------------------------------------------------------------------------
def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"{path} is not valid YAML: {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"{path} could not be read: {exc.strerror or exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path} must contain a mapping at the top level.")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` updated with ``override``; nested mappings are merged."""
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _check_yaml_layer(data: dict[str, Any], source: Path) -> None:
    unknown = sorted(set(data) - set(Settings.model_fields))
    if unknown:
        raise ConfigurationError(
            f"{source} contains unknown setting(s): {', '.join(unknown)}.",
            hint=f"Known top-level settings: {', '.join(sorted(Settings.model_fields))}.",
        )
    for section, key in SECRET_YAML_PATHS:
        section_data = data.get(section)
        if isinstance(section_data, dict) and section_data.get(key) is not None:
            raise ConfigurationError(
                f"{source} sets {section}.{key}, which is a secret and must not be stored "
                "in a settings file.",
                hint=(
                    f"Use the environment variable {ENV_PREFIX}{section.upper()}__{key.upper()} "
                    f"or run: omniosint secrets set {section}.{key}"
                ),
            )


def config_files(paths: AppPaths) -> list[tuple[str, Path, bool]]:
    """Describe every configuration file, in ascending priority.

    Returns ``(label, path, exists)`` tuples.
    """
    defaults = default_config_dir()
    root = project_root()
    files: list[tuple[str, Path]] = [
        ("defaults", defaults / "settings.yaml"),
        ("logging defaults", defaults / "logging.yaml"),
        ("user settings", paths.user_settings_file),
        ("data directory .env", paths.env_file),
    ]
    if root is not None:
        files.append(("project .env", root / ".env"))
    return [(label, path, path.is_file()) for label, path in files]


def load_yaml_layers(paths: AppPaths) -> dict[str, Any]:
    """Load and merge the YAML configuration files."""
    defaults = default_config_dir()
    merged: dict[str, Any] = {}

    settings_default = defaults / "settings.yaml"
    if settings_default.is_file():
        data = _read_yaml(settings_default)
        _check_yaml_layer(data, settings_default)
        merged = deep_merge(merged, data)

    logging_default = defaults / "logging.yaml"
    if logging_default.is_file():
        data = _read_yaml(logging_default)
        merged = deep_merge(merged, {"logging": data})

    if paths.user_settings_file.is_file():
        data = _read_yaml(paths.user_settings_file)
        _check_yaml_layer(data, paths.user_settings_file)
        merged = deep_merge(merged, data)
    return merged


def _format_validation_error(exc: ValidationError) -> ConfigurationError:
    details = []
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        message = error["msg"].removeprefix("Value error, ")
        details.append({"setting": location, "message": message})
        lines.append(f"  {location}: {message}")
    return ConfigurationError(
        "The configuration is invalid:\n" + "\n".join(lines),
        details=details,
        hint="Run `omniosint config paths` to see which files are read.",
    )


def load_settings(
    paths: AppPaths | None = None,
    *,
    overrides: dict[str, Any] | None = None,
    use_files: bool = True,
) -> Settings:
    """Build the effective settings.

    ``use_files=False`` ignores YAML and ``.env`` files (used by tests that need
    a hermetic configuration).
    """
    resolved_paths = paths or AppPaths.resolve()
    layer: dict[str, Any] = load_yaml_layers(resolved_paths) if use_files else {}

    env_files: list[Path] = []
    if use_files:
        env_files.append(resolved_paths.env_file)
        root = project_root()
        if root is not None:
            env_files.append(root / ".env")

    token = _yaml_layer.set(layer)
    try:
        return Settings(
            _env_file=tuple(str(path) for path in env_files) or None,
            _env_file_encoding="utf-8",
            **(overrides or {}),
        )
    except ValidationError as exc:
        raise _format_validation_error(exc) from exc
    finally:
        _yaml_layer.reset(token)
