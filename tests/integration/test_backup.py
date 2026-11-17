from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from omniosint.audit.service import CLI_ACTOR
from omniosint.auth.passwords import PasswordHasher
from omniosint.backup import pgtools
from omniosint.backup import service as backup
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict
from omniosint.core.paths import AppPaths
from omniosint.database.engine import Database
from omniosint.users.service import UserService
from tests.helpers import USER_PASSWORD, fetch_all, run_sync

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        any(pgtools.find_tool(tool) is None for tool in ("pg_dump", "pg_restore", "psql")),
        reason="PostgreSQL client tools are not installed",
    ),
]


def add_user(settings: Settings, paths: AppPaths, username: str) -> None:
    async def create() -> None:
        db = Database.from_settings(settings, paths)
        users = UserService(settings.auth, PasswordHasher(settings.auth))
        try:
            async with db.session() as session:
                await users.create_user(
                    session,
                    actor=CLI_ACTOR,
                    username=username,
                    display_name="",
                    email=None,
                    password=USER_PASSWORD,
                    roles=["viewer"],
                )
        finally:
            await db.dispose()

    run_sync(create)


def usernames(database_url: str) -> list[str]:
    rows = run_sync(lambda: fetch_all(database_url, "SELECT username FROM users ORDER BY 1"))
    return [row[0] for row in rows]


def test_backup_and_restore_round_trip(
    db_settings: Settings, app_paths: AppPaths, clean_database: str
):
    add_user(db_settings, app_paths, "kept")
    info = backup.create_backup(db_settings, app_paths, label="test")
    assert info.path.parent == app_paths.backups_dir
    assert info.schema_revision is not None
    assert backup.verify_backup(info.path).files == info.files

    add_user(db_settings, app_paths, "added_later")
    assert usernames(clean_database) == ["added_later", "kept"]

    result = backup.restore_backup(db_settings, app_paths, info.path)
    assert usernames(clean_database) == ["kept"]
    assert result.safety_backup is not None and result.safety_backup.path.is_file()
    backup.verify_backup(result.safety_backup.path)
    restored_events = run_sync(
        lambda: fetch_all(
            clean_database,
            "SELECT details->>'name' FROM audit_events WHERE action = 'backup.restored'",
        )
    )
    assert restored_events == [(info.path.name,)]

    names = [item.path.name for item in backup.list_backups(app_paths)]
    assert names[0] == result.safety_backup.path.name, "newest first"
    assert info.path.name in names


def _rewrite_archive(source: Path, target: Path, *, manifest_changes: dict[str, object]) -> None:
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as rewritten:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == backup.MANIFEST_NAME:
                manifest = json.loads(data)
                manifest.update(manifest_changes)
                data = json.dumps(manifest).encode()
            rewritten.writestr(item, data)


def test_restore_refuses_a_backup_from_a_newer_version(
    db_settings: Settings, app_paths: AppPaths, tmp_path: Path
):
    info = backup.create_backup(db_settings, app_paths)
    newer = tmp_path / "omniosint-backup-newer.zip"
    _rewrite_archive(info.path, newer, manifest_changes={"schema_revision": "9999"})
    with pytest.raises(Conflict, match="newer version"):
        backup.restore_backup(db_settings, app_paths, newer, safety_backup=False)


def test_verify_rejects_damaged_or_foreign_archives(
    db_settings: Settings, app_paths: AppPaths, tmp_path: Path
):
    info = backup.create_backup(db_settings, app_paths)

    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(info.path) as original, zipfile.ZipFile(damaged, "w") as copy:
        for item in original.infolist():
            data = original.read(item.filename)
            if item.filename == backup.DUMP_NAME:
                data = data[:-4] + b"XXXX"
            copy.writestr(item, data)
    with pytest.raises(backup.BackupInvalid, match="integrity"):
        backup.verify_backup(damaged)

    foreign = tmp_path / "foreign.zip"
    _rewrite_archive(
        info.path,
        foreign,
        manifest_changes={
            "files": [{"name": "../../evil.txt", "size": 1, "sha256": "0"}],
        },
    )
    with pytest.raises(backup.BackupInvalid):
        backup.verify_backup(foreign)

    not_zip = tmp_path / "not.zip"
    not_zip.write_text("plain text", encoding="utf-8")
    with pytest.raises(backup.BackupInvalid, match="not a readable"):
        backup.verify_backup(not_zip)


def test_listing_skips_unreadable_archives(app_paths: AppPaths):
    app_paths.backups_dir.mkdir(parents=True, exist_ok=True)
    (app_paths.backups_dir / "omniosint-backup-garbage.zip").write_text("x", encoding="utf-8")
    assert backup.list_backups(app_paths) == []
