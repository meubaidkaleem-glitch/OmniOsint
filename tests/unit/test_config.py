from __future__ import annotations

from pathlib import Path

import pytest

from omniosint.core.config import (
    Settings,
    config_files,
    deep_merge,
    is_loopback_host,
    load_settings,
)
from omniosint.core.errors import ConfigurationError
from omniosint.core.paths import AppPaths


def write_user_settings(paths: AppPaths, content: str) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.user_settings_file.write_text(content, encoding="utf-8")


def test_defaults_are_local_only_and_production(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths, use_files=False)
    assert settings.environment == "production"
    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 8765
    assert settings.server.allow_non_loopback is False
    assert settings.server.base_url == "http://127.0.0.1:8765"
    assert settings.auth.cookie_secure is False
    assert settings.docs_enabled is False


def test_shipped_default_files_load_and_are_valid(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths)
    assert settings.logging.level == "INFO"
    assert settings.database.name == "omniosint"
    labels = {label for label, _path, exists in config_files(app_paths) if exists}
    assert {"defaults", "logging defaults"} <= labels


def test_user_settings_override_defaults(app_paths: AppPaths) -> None:
    write_user_settings(app_paths, "server:\n  port: 9100\nlogging:\n  level: DEBUG\n")
    settings = load_settings(app_paths)
    assert settings.server.port == 9100
    assert settings.logging.level == "DEBUG"
    # Untouched keys keep their defaults.
    assert settings.server.host == "127.0.0.1"


def test_environment_overrides_user_settings(
    app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_user_settings(app_paths, "server:\n  port: 9100\n")
    monkeypatch.setenv("OMNIOSINT_SERVER__PORT", "9200")
    assert load_settings(app_paths).server.port == 9200


def test_unknown_top_level_key_is_rejected(app_paths: AppPaths) -> None:
    write_user_settings(app_paths, "sever:\n  port: 9000\n")
    with pytest.raises(ConfigurationError, match="unknown setting"):
        load_settings(app_paths)


def test_unknown_nested_key_is_rejected(app_paths: AppPaths) -> None:
    write_user_settings(app_paths, "server:\n  prot: 9000\n")
    with pytest.raises(ConfigurationError) as caught:
        load_settings(app_paths)
    assert any(detail["setting"] == "server.prot" for detail in caught.value.details)


@pytest.mark.parametrize(("section", "key"), [("database", "password"), ("database", "url")])
def test_secrets_in_yaml_are_refused(app_paths: AppPaths, section: str, key: str) -> None:
    write_user_settings(app_paths, f"{section}:\n  {key}: hunter2hunter2\n")
    with pytest.raises(ConfigurationError, match="secret") as caught:
        load_settings(app_paths)
    assert "hunter2" not in caught.value.message
    assert caught.value.hint is not None and "secrets set" in caught.value.hint


def test_invalid_yaml_is_reported(app_paths: AppPaths) -> None:
    write_user_settings(app_paths, "server: [unclosed\n")
    with pytest.raises(ConfigurationError, match="not valid YAML"):
        load_settings(app_paths)


def test_out_of_range_value_is_reported_with_its_location(app_paths: AppPaths) -> None:
    with pytest.raises(ConfigurationError) as caught:
        load_settings(app_paths, overrides={"server": {"port": 80}}, use_files=False)
    assert caught.value.details[0]["setting"] == "server.port"


def test_non_loopback_host_requires_explicit_opt_in(app_paths: AppPaths) -> None:
    with pytest.raises(ConfigurationError, match="loopback"):
        load_settings(app_paths, overrides={"server": {"host": "0.0.0.0"}}, use_files=False)  # noqa: S104
    settings = load_settings(
        app_paths,
        overrides={"server": {"host": "0.0.0.0", "allow_non_loopback": True}},  # noqa: S104
        use_files=False,
    )
    assert settings.server.base_url == "http://127.0.0.1:8765"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("127.5.6.7", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("LOCALHOST", True),
        ("0.0.0.0", False),  # noqa: S104
        ("192.168.1.10", False),
        ("example.com", False),
        ("::", False),
    ],
)
def test_is_loopback_host(host: str, expected: bool) -> None:
    assert is_loopback_host(host) is expected


def test_ipv6_base_url_is_bracketed(app_paths: AppPaths) -> None:
    settings = load_settings(app_paths, overrides={"server": {"host": "::1"}}, use_files=False)
    assert settings.server.base_url == "http://[::1]:8765"


def test_public_dict_masks_secrets(app_paths: AppPaths) -> None:
    settings = load_settings(
        app_paths,
        overrides={"database": {"password": "s3cret-value-here"}},
        use_files=False,
    )
    dumped = str(settings.public_dict())
    assert "s3cret-value-here" not in dumped
    assert settings.database.password is not None
    assert settings.database.password.get_secret_value() == "s3cret-value-here"


def test_dotenv_in_data_directory_is_read(app_paths: AppPaths) -> None:
    app_paths.env_file.write_text("OMNIOSINT_SERVER__PORT=9300\n", encoding="utf-8")
    assert load_settings(app_paths).server.port == 9300


def test_deep_merge() -> None:
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    merged = deep_merge(base, {"a": {"c": 20, "e": 5}, "f": 6})
    assert merged == {"a": {"b": 1, "c": 20, "e": 5}, "d": 3, "f": 6}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}


def test_settings_are_immutable(settings: Settings) -> None:
    with pytest.raises(Exception, match="frozen"):
        settings.server.port = 1  # type: ignore[misc]


def test_paths_are_separate_from_program(tmp_path: Path) -> None:
    paths = AppPaths.resolve(tmp_path / "data-home")
    paths.ensure()
    assert paths.logs_dir.is_dir() and paths.backups_dir.is_dir() and paths.secrets_dir.is_dir()
    assert paths.user_settings_file.parent == paths.config_dir
