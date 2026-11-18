from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from pathlib import Path

import pytest

from omniosint.audit.service import CLI_ACTOR
from omniosint.auth.passwords import PasswordHasher
from omniosint.backup import pgtools
from omniosint.backup import service as backup
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict
from omniosint.core.paths import AppPaths
from omniosint.core.secrets import SecretStore
from omniosint.database.engine import Database
from omniosint.database.models import RawObject
from omniosint.evidence.objectstore import ENCRYPTION, ObjectStore
from omniosint.users.service import UserService
from tests.helpers import USER_PASSWORD, fetch_all, make_settings, run_sync

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


# --------------------------------------------------------------------------- raw responses
def open_store(paths: AppPaths) -> ObjectStore:
    return ObjectStore.open(paths.objects_dir, SecretStore(paths))


def store_raw(settings: Settings, paths: AppPaths, *contents: bytes) -> list[str]:
    """Store raw responses the way the collector does: bytes first, then the record."""
    store = open_store(paths)
    stored = [store.put(content) for content in contents]

    async def insert() -> None:
        db = Database.from_settings(settings, paths)
        try:
            async with db.session() as session:
                for item in stored:
                    session.add(
                        RawObject(
                            sha256=item.sha256,
                            size=item.size,
                            content_type="application/json",
                            encryption=ENCRYPTION,
                        )
                    )
                await session.commit()
        finally:
            await db.dispose()

    run_sync(insert)
    return [item.sha256 for item in stored]


def raw_members(archive_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(archive_path) as archive:
        return {
            name.removeprefix(backup.OBJECTS_PREFIX): archive.read(name)
            for name in archive.namelist()
            if name.startswith(backup.OBJECTS_PREFIX)
        }


FIRST = b'{"response": "first", "padding": "' + b"x" * 2000 + b'"}'
SECOND = b'{"response": "second"}'
LATER = b'{"response": "stored after the backup"}'


def test_raw_responses_are_backed_up_and_restored(
    db_settings: Settings, app_paths: AppPaths, clean_database: str
):
    first, second = store_raw(db_settings, app_paths, FIRST, SECOND)
    info = backup.create_backup(db_settings, app_paths)
    assert (info.format, info.raw_responses, info.raw_responses_included) == (2, 2, True)
    # Exported decrypted, so the archive can be restored under another key.
    assert raw_members(info.path) == {first: FIRST, second: SECOND}

    store = open_store(app_paths)
    (later,) = store_raw(db_settings, app_paths, LATER)
    store.delete(first)  # lost locally after the backup was made

    result = backup.restore_backup(db_settings, app_paths, info.path)
    assert result.raw == backup.RawRestore(restored=2, already_present=0, missing=0, removed=1)
    assert store.get(first) == FIRST and store.get(second) == SECOND
    assert not store.exists(later), "nothing refers to it after the restore"
    restored_rows = run_sync(
        lambda: fetch_all(clean_database, "SELECT sha256 FROM raw_objects ORDER BY 1")
    )
    assert [row[0] for row in restored_rows] == sorted([first, second])

    # The safety backup kept what was there before, and says what it could not read.
    assert result.safety_backup is not None
    safety = backup.verify_backup(result.safety_backup.path)
    assert (safety.raw_responses, safety.raw_responses_not_exported) == (2, 1)
    assert set(raw_members(safety.path)) == {second, later}

    details = run_sync(
        lambda: fetch_all(
            clean_database,
            "SELECT details->'raw_responses' FROM audit_events WHERE action = 'backup.restored'",
        )
    )
    assert details == [({"restored": 2, "already_present": 0, "missing": 0, "removed": 1},)]


def test_restore_on_another_installation_encrypts_under_its_own_key(
    db_settings: Settings, app_paths: AppPaths, clean_database: str, tmp_path: Path
):
    (sha,) = store_raw(db_settings, app_paths, FIRST)
    info = backup.create_backup(db_settings, app_paths)

    other_paths = AppPaths.resolve(tmp_path / "other-installation")
    other_paths.ensure()
    other_settings = make_settings(other_paths, clean_database)
    result = backup.restore_backup(other_settings, other_paths, info.path, safety_backup=False)
    assert result.raw.restored == 1

    other = open_store(other_paths)
    assert other.get(sha) == FIRST
    original_files = {path.name for path in open_store(app_paths).files()}
    other_files = {path.name for path in other.files()}
    assert len(other_files) == 1 and not other_files & original_files, "different key, names"


def test_backup_without_raw_responses(
    db_settings: Settings, app_paths: AppPaths, clean_database: str
):
    first, second = store_raw(db_settings, app_paths, FIRST, SECOND)
    info = backup.create_backup(db_settings, app_paths, include_raw=False)
    assert (info.raw_responses, info.raw_responses_included) == (0, False)
    assert raw_members(info.path) == {}

    store = open_store(app_paths)
    store.delete(second)
    result = backup.restore_backup(db_settings, app_paths, info.path, safety_backup=False)
    # The local copy is kept; the one lost locally cannot come from this backup.
    assert result.raw == backup.RawRestore(restored=0, already_present=1, missing=1, removed=0)
    assert store.get(first) == FIRST


def test_an_archive_from_phase_1_still_restores(
    db_settings: Settings, app_paths: AppPaths, clean_database: str, tmp_path: Path
):
    (sha,) = store_raw(db_settings, app_paths, FIRST)
    current = backup.create_backup(db_settings, app_paths)
    old_format = tmp_path / "omniosint-backup-phase1.zip"
    with zipfile.ZipFile(current.path) as original, zipfile.ZipFile(old_format, "w") as copy:
        for item in original.infolist():
            if item.filename.startswith(backup.OBJECTS_PREFIX):
                continue
            data = original.read(item.filename)
            if item.filename == backup.MANIFEST_NAME:
                manifest = json.loads(data)
                manifest["format"] = 1
                del manifest["raw_responses"]
                data = json.dumps(manifest).encode()
            copy.writestr(item, data)
    info = backup.verify_backup(old_format)
    assert (info.format, info.raw_responses) == (1, 0)
    result = backup.restore_backup(db_settings, app_paths, old_format, safety_backup=False)
    assert result.raw == backup.RawRestore(restored=0, already_present=1, missing=0, removed=0)
    assert open_store(app_paths).get(sha) == FIRST


def _copy_with(source: Path, target: Path, change: Callable[[str, bytes], bytes | None]) -> None:
    """Copy an archive, passing each member through ``change`` (None drops it)."""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as copy:
        for item in original.infolist():
            data = change(item.filename, original.read(item.filename))
            if data is not None:
                copy.writestr(item, data)


def test_verify_checks_every_raw_response(
    db_settings: Settings, app_paths: AppPaths, tmp_path: Path
):
    first, _second = store_raw(db_settings, app_paths, FIRST, SECOND)
    info = backup.create_backup(db_settings, app_paths)
    member = backup.OBJECTS_PREFIX + first

    modified = tmp_path / "modified.zip"
    _copy_with(info.path, modified, lambda name, data: data + b" " if name == member else data)
    with pytest.raises(backup.BackupInvalid, match=f"raw response {first} was modified"):
        backup.verify_backup(modified)

    missing = tmp_path / "missing.zip"
    _copy_with(info.path, missing, lambda name, data: None if name == member else data)
    with pytest.raises(backup.BackupInvalid, match="missing or were replaced"):
        backup.verify_backup(missing)

    unexpected = tmp_path / "unexpected.zip"
    _copy_with(info.path, unexpected, lambda name, data: data)
    with zipfile.ZipFile(unexpected, "a") as archive:
        archive.writestr("objects/../../escape.txt", b"x")
    with pytest.raises(backup.BackupInvalid, match="unexpected file"):
        backup.verify_backup(unexpected)
