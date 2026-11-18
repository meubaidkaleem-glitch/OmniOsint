"""Backup and restore.

A backup is one zip archive holding a PostgreSQL custom-format dump, the user
settings file, the stored raw responses and a manifest with checksums. Secrets
are not included: the secret store is bound to the machine and account that
created it.

Raw responses are kept encrypted under the installation's object key, which
lives in the secret store. A backup therefore exports them decrypted, one
archive member per response named by its SHA-256, and a restore encrypts them
again under the key of the installation it runs on. They can be left out with
``include_raw=False``.

Restore is atomic for the database: the dump is converted to SQL and applied in
a single transaction together with the removal of the existing objects, so a
failed restore leaves the database exactly as it was. The raw responses are
written once the database has been restored, and the object store is then
reduced to what the restored database refers to.

Limitation (documented in SECURITY.md): archives are not encrypted in this
phase. Passphrase encryption arrives in Phase 13.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory
from sqlalchemy import text

from omniosint import __version__
from omniosint.audit.service import CLI_ACTOR, Actor, record
from omniosint.backup import pgtools
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict, OmniError, ValidationFailed
from omniosint.core.logging import get_logger
from omniosint.core.paths import AppPaths, restrict_to_owner
from omniosint.core.secrets import SecretStore, SecretStoreError
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database import migrate
from omniosint.database.engine import Database, build_database_url, ssl_mode_for
from omniosint.database.seeds import seed_builtin
from omniosint.evidence.objectstore import (
    ObjectStore,
    ObjectStoreError,
    object_files,
    sha256_hex,
)

log = get_logger(__name__)

FORMAT_VERSION = 2
# Format 1 archives (Phase 1) hold no raw responses; they can still be restored.
_READABLE_FORMATS = frozenset({1, 2})
MANIFEST_NAME = "manifest.json"
DUMP_NAME = "database.dump"
SETTINGS_NAME = "config/settings.yaml"
OBJECTS_PREFIX = "objects/"
_OBJECT_MEMBER = re.compile(r"^objects/([0-9a-f]{64})$")
_ARCHIVE_PREFIX = "omniosint-backup-"
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_CHUNK = 1024 * 1024
_SAMPLE_LIMIT = 100

# Removes every object the application owns in the public schema, leaving
# extension members alone. Runs inside the restore transaction.
_DROP_EXISTING_OBJECTS = """
DO $restore$
DECLARE item record;
BEGIN
    FOR item IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
        EXECUTE format('DROP TABLE IF EXISTS public.%I CASCADE', item.tablename);
    END LOOP;
    FOR item IN
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'S'
    LOOP
        EXECUTE format('DROP SEQUENCE IF EXISTS public.%I CASCADE', item.relname);
    END LOOP;
    FOR item IN
        SELECT p.oid::regprocedure::text AS signature
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = p.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('DROP ROUTINE IF EXISTS %s CASCADE', item.signature);
    END LOOP;
    FOR item IN
        SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd')
          AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.objid = t.oid AND d.deptype = 'e')
    LOOP
        EXECUTE format('DROP TYPE IF EXISTS public.%I CASCADE', item.typname);
    END LOOP;
END
$restore$;
"""


class BackupInvalid(ValidationFailed):
    code = "backup_invalid"
    default_message = "The backup archive is not valid."


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    created_at: str
    app_version: str
    schema_revision: str | None
    server_version: str
    size_bytes: int
    label: str | None
    files: list[dict[str, Any]]
    format: int = FORMAT_VERSION
    raw_responses: int = 0
    raw_responses_included: bool = False
    raw_responses_not_exported: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "name": self.path.name,
            "created_at": self.created_at,
            "app_version": self.app_version,
            "schema_revision": self.schema_revision,
            "server_version": self.server_version,
            "size_bytes": self.size_bytes,
            "label": self.label,
            "format": self.format,
            "raw_responses": {
                "included": self.raw_responses_included,
                "count": self.raw_responses,
                "not_exported": self.raw_responses_not_exported,
            },
        }


@dataclass(frozen=True, slots=True)
class RawRestore:
    """What happened to the raw responses during a restore."""

    restored: int = 0
    already_present: int = 0
    missing: int = 0
    removed: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "restored": self.restored,
            "already_present": self.already_present,
            "missing": self.missing,
            "removed": self.removed,
        }


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_from: BackupInfo
    safety_backup: BackupInfo | None
    schema_revision: str | None
    raw: RawRestore = field(default_factory=RawRestore)


@dataclass(frozen=True, slots=True)
class _Export:
    hashes: list[str]
    size: int
    failed: list[str]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _member_sha256(archive: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    with archive.open(member) as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _index_digest(hashes: Iterable[str]) -> str:
    """One digest over the set of raw responses, so a missing or swapped member is noticed."""
    return hashlib.sha256("\n".join(sorted(hashes)).encode("ascii")).hexdigest()


def _known_revisions() -> set[str]:
    script = ScriptDirectory.from_config(migrate.alembic_config())
    return {revision.revision for revision in script.walk_revisions()}


async def _database_facts(settings: Settings, paths: AppPaths) -> tuple[str | None, int, str]:
    db = Database.from_settings(settings, paths, application_name="omniosint-backup")
    try:
        revision = await migrate.current_revision(db.engine)
        number, label = await db.server_version()
    finally:
        await db.dispose()
    return revision, number, label


async def _raw_object_hashes(settings: Settings, paths: AppPaths) -> list[str]:
    """Hashes of the raw responses the database refers to."""
    db = Database.from_settings(settings, paths, application_name="omniosint-backup")
    try:
        async with db.engine.connect() as connection:
            present = await connection.scalar(
                text("SELECT to_regclass('public.raw_objects') IS NOT NULL")
            )
            if not present:  # a database not yet migrated to Phase 2
                return []
            result = await connection.execute(text("SELECT sha256 FROM raw_objects ORDER BY 1"))
            return [str(row[0]) for row in result]
    finally:
        await db.dispose()


def _open_store(paths: AppPaths, *, hint: str) -> ObjectStore:
    try:
        return ObjectStore.open(paths.objects_dir, SecretStore(paths))
    except (SecretStoreError, OSError) as error:
        raise OmniError(
            f"The stored raw responses cannot be read or written: their key is in the secret "
            f"store, which could not be opened ({error}).",
            hint=hint,
        ) from error


async def _record_event(
    settings: Settings, paths: AppPaths, action: str, actor: Actor, details: dict[str, Any]
) -> None:
    db = Database.from_settings(settings, paths, application_name="omniosint-backup")
    try:
        async with db.session() as session:
            record(session, action=action, actor=actor, target_type="backup", details=details)
            await session.commit()
    except Exception as exc:
        log.warning("backup.audit_failed", action=action, error=type(exc).__name__)
    finally:
        await db.dispose()


def _create_private_file(path: Path) -> None:
    """Create an empty file only the current user can read, before anything is
    written to it (the archive holds password hashes and raw responses)."""
    path.unlink(missing_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    restrict_to_owner(path)


def _export_objects(
    archive: zipfile.ZipFile, store: ObjectStore | None, hashes: Iterable[str]
) -> _Export:
    exported: list[str] = []
    failed: list[str] = []
    size = 0
    for sha256 in hashes:
        try:
            if store is None:
                raise ObjectStoreError("no object store")
            content = store.get(sha256)  # decrypts and checks the content against its hash
        except ObjectStoreError as error:
            log.warning("backup.raw_unreadable", sha256=sha256, error=type(error).__name__)
            failed.append(sha256)
            continue
        archive.writestr(OBJECTS_PREFIX + sha256, content)
        exported.append(sha256)
        size += len(content)
    return _Export(exported, size, failed)


def create_backup(
    settings: Settings,
    paths: AppPaths,
    *,
    output_dir: Path | None = None,
    label: str | None = None,
    include_raw: bool = True,
    actor: Actor = CLI_ACTOR,
) -> BackupInfo:
    """Create a backup archive and return its description.

    Raw responses the store cannot read (missing or damaged) are left out and
    counted in the manifest; the rest of the backup is still made.
    """
    if label is not None and not _LABEL_PATTERN.fullmatch(label):
        raise ValidationFailed(
            "A backup label may contain letters, digits, hyphens and underscores (max 32)."
        )
    pg_dump = pgtools.require_tool("pg_dump", settings.database)
    tool_major, tool_version_text = pgtools.tool_version(pg_dump)
    revision, server_number, server_label = asyncio.run(_database_facts(settings, paths))
    server_major = server_number // 10000
    if tool_major < server_major:
        raise OmniError(
            f"pg_dump {tool_major} cannot back up a PostgreSQL {server_major} server.",
            hint="Install client tools at least as new as the server, or set database.pg_bin_dir.",
        )

    destination_dir = output_dir or paths.backups_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    now = utcnow()
    stamp = now.strftime("%Y%m%d-%H%M%SZ")
    name = f"{_ARCHIVE_PREFIX}{stamp}{'-' + label if label else ''}.zip"
    archive_path = destination_dir / name
    if archive_path.exists():
        raise Conflict(f"A backup named {name} already exists.")

    url = build_database_url(settings, paths)
    environment = pgtools.connection_environment(url, ssl_mode_for(settings.database))
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.run_dir, prefix="backup-") as tmp:
        workdir = Path(tmp)
        dump_path = workdir / DUMP_NAME
        pgtools.run_tool(
            pg_dump,
            ["--format=custom", "--no-owner", "--no-privileges", "--file", str(dump_path)],
            environment=environment,
            action="The database backup",
        )
        members: list[tuple[str, Path]] = [(DUMP_NAME, dump_path)]
        if paths.user_settings_file.is_file():
            members.append((SETTINGS_NAME, paths.user_settings_file))

        # Listed after the dump: a response stored meanwhile is exported but not
        # referenced (the restore skips it); one deleted meanwhile had passed its
        # retention period and is reported as not exported.
        hashes = asyncio.run(_raw_object_hashes(settings, paths)) if include_raw else []
        store = (
            _open_store(
                paths,
                hint="Repair the secret store (see `omniosint doctor`), or back up without "
                "raw responses (--no-raw-responses).",
            )
            if hashes
            else None
        )

        partial = archive_path.with_suffix(".zip.partial")
        try:
            _create_private_file(partial)
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                for member, source in members:
                    archive.write(source, arcname=member)
                export = _export_objects(archive, store, hashes)
                manifest = {
                    "format": FORMAT_VERSION,
                    "created_at": isoformat(now),
                    "app_version": __version__,
                    "schema_revision": revision,
                    "server_version": server_label,
                    "pg_dump_version": tool_version_text,
                    "label": label,
                    "encrypted": False,
                    "files": [
                        {"name": member, "size": source.stat().st_size, "sha256": _sha256(source)}
                        for member, source in members
                    ],
                    "raw_responses": {
                        "included": include_raw,
                        "count": len(export.hashes),
                        "size": export.size,
                        "index_sha256": _index_digest(export.hashes),
                        "not_exported": len(export.failed),
                        "not_exported_sample": export.failed[:_SAMPLE_LIMIT],
                    },
                }
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
            partial.replace(archive_path)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
    restrict_to_owner(archive_path)

    info = verify_backup(archive_path)
    asyncio.run(
        _record_event(
            settings,
            paths,
            "backup.created",
            actor,
            {
                "name": archive_path.name,
                "size_bytes": info.size_bytes,
                "label": label,
                "raw_responses": info.raw_responses,
                "raw_responses_included": include_raw,
                "raw_responses_not_exported": info.raw_responses_not_exported,
            },
        )
    )
    return info


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def _read_manifest(archive: zipfile.ZipFile, path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise BackupInvalid(f"{path.name} has no readable manifest.") from exc
    if not isinstance(manifest, dict):
        raise BackupInvalid(f"{path.name} uses an unsupported backup format.")
    version = manifest.get("format")
    if type(version) is not int or version not in _READABLE_FORMATS:
        raise BackupInvalid(f"{path.name} uses an unsupported backup format.")
    files = manifest.get("files")
    if not isinstance(files, list) or not any(
        isinstance(item, dict) and item.get("name") == DUMP_NAME for item in files
    ):
        raise BackupInvalid(f"{path.name} does not contain a database dump.")
    if version >= 2:
        raw = manifest.get("raw_responses")
        if not (
            isinstance(raw, dict)
            and isinstance(raw.get("included"), bool)
            and _is_count(raw.get("count"))
            and _is_count(raw.get("not_exported"))
            and isinstance(raw.get("index_sha256"), str)
        ):
            raise BackupInvalid(f"{path.name} has an incomplete manifest.")
    return manifest


def _raw_summary(manifest: dict[str, Any]) -> dict[str, Any] | None:
    raw = manifest.get("raw_responses") if manifest["format"] >= 2 else None
    return raw if isinstance(raw, dict) else None


def _info_from(path: Path, manifest: dict[str, Any]) -> BackupInfo:
    raw = _raw_summary(manifest)
    return BackupInfo(
        path=path,
        created_at=str(manifest.get("created_at", "")),
        app_version=str(manifest.get("app_version", "")),
        schema_revision=manifest.get("schema_revision"),
        server_version=str(manifest.get("server_version", "")),
        size_bytes=path.stat().st_size,
        label=manifest.get("label"),
        files=list(manifest["files"]),
        format=int(manifest["format"]),
        raw_responses=int(raw["count"]) if raw else 0,
        raw_responses_included=bool(raw["included"]) if raw else False,
        raw_responses_not_exported=int(raw["not_exported"]) if raw else 0,
    )


def verify_backup(path: Path) -> BackupInfo:
    """Check an archive's structure and checksums, raw responses included."""
    if not path.is_file():
        raise BackupInvalid(f"{path} does not exist.")
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = _read_manifest(archive, path)
            for entry in manifest["files"]:
                member = str(entry.get("name", ""))
                # Only names this module writes are ever read from an archive.
                if member not in (DUMP_NAME, SETTINGS_NAME):
                    raise BackupInvalid(f"{path.name} lists an unexpected file: {member!r}.")
                try:
                    digest = _member_sha256(archive, member)
                except KeyError as exc:
                    raise BackupInvalid(f"{path.name} is missing {member}.") from exc
                if digest != entry.get("sha256"):
                    raise BackupInvalid(
                        f"{path.name} failed its integrity check ({member} was modified)."
                    )
            raw = _raw_summary(manifest)
            found: list[str] = []
            for member in archive.namelist():
                if not member.startswith(OBJECTS_PREFIX):
                    continue
                match = _OBJECT_MEMBER.fullmatch(member)
                if match is None or raw is None:
                    raise BackupInvalid(f"{path.name} contains an unexpected file: {member!r}.")
                if _member_sha256(archive, member) != match.group(1):
                    raise BackupInvalid(
                        f"{path.name} failed its integrity check "
                        f"(raw response {match.group(1)} was modified)."
                    )
                found.append(match.group(1))
            if raw is not None and (
                len(found) != raw["count"] or _index_digest(found) != raw["index_sha256"]
            ):
                raise BackupInvalid(
                    f"{path.name} failed its integrity check "
                    "(raw responses are missing or were replaced)."
                )
    except zipfile.BadZipFile as exc:
        raise BackupInvalid(f"{path.name} is not a readable backup archive.") from exc
    return _info_from(path, manifest)


def list_backups(paths: AppPaths, directory: Path | None = None) -> list[BackupInfo]:
    """Backups in the backup directory, newest first. Unreadable archives are skipped."""
    folder = directory or paths.backups_dir
    if not folder.is_dir():
        return []
    found: list[BackupInfo] = []
    for candidate in folder.glob(f"{_ARCHIVE_PREFIX}*.zip"):
        try:
            with zipfile.ZipFile(candidate) as archive:
                found.append(_info_from(candidate, _read_manifest(archive, candidate)))
        except (BackupInvalid, zipfile.BadZipFile, OSError):
            continue
    return sorted(found, key=lambda item: item.created_at, reverse=True)


def _restore_objects(
    archive_path: Path, info: BackupInfo, store: ObjectStore | None, referenced: list[str]
) -> tuple[RawRestore, str | None]:
    """Write the raw responses the restored database refers to, then remove the
    ones it does not. Returns the counts and, if writing failed, why."""
    if store is None:  # neither the archive nor this installation holds any
        return RawRestore(missing=len(referenced)), None
    restored = present = missing = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist()) if info.raw_responses else set()
            for sha256 in referenced:
                member = OBJECTS_PREFIX + sha256
                if member in names:
                    content = archive.read(member)
                    if sha256_hex(content) != sha256:
                        raise BackupInvalid(f"Raw response {sha256} changed after verification.")
                    store.put(content, overwrite=True)  # under this installation's key
                    restored += 1
                elif store.exists(sha256):
                    present += 1
                else:
                    missing += 1
        removed = store.prune(referenced)
    except (OSError, zipfile.BadZipFile, BackupInvalid) as error:
        return RawRestore(restored, present, missing), str(error)
    return RawRestore(restored, present, missing, removed), None


def restore_backup(
    settings: Settings,
    paths: AppPaths,
    archive_path: Path,
    *,
    safety_backup: bool = True,
    restore_settings: bool = False,
    actor: Actor = CLI_ACTOR,
) -> RestoreResult:
    """Replace the database content and the stored raw responses with a backup.

    The caller is responsible for confirming with the user and for making sure
    OmniOSINT is stopped; ``omniosint backup restore`` does both.
    """
    info = verify_backup(archive_path)
    if info.schema_revision is not None and info.schema_revision not in _known_revisions():
        raise Conflict(
            f"This backup was made by a newer version of OmniOSINT (schema revision "
            f"{info.schema_revision}).",
            hint="Update OmniOSINT, then restore again.",
        )
    pg_restore = pgtools.require_tool("pg_restore", settings.database)
    psql = pgtools.require_tool("psql", settings.database)

    # Raw responses are written under this installation's key, and responses the
    # restored database does not refer to are removed. Open the store before
    # anything changes, so a broken secret store stops the restore early.
    store: ObjectStore | None = None
    if info.raw_responses or next(object_files(paths.objects_dir), None) is not None:
        store = _open_store(
            paths, hint="Repair the secret store (see `omniosint doctor`), then restore again."
        )

    safety: BackupInfo | None = None
    if safety_backup:
        safety = create_backup(settings, paths, label="pre-restore", actor=actor)

    url = build_database_url(settings, paths)
    environment = pgtools.connection_environment(url, ssl_mode_for(settings.database))
    paths.run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.run_dir, prefix="restore-") as tmp:
        workdir = Path(tmp)
        dump_path = workdir / DUMP_NAME
        with (
            zipfile.ZipFile(archive_path) as archive,
            archive.open(DUMP_NAME) as source,
            dump_path.open("wb") as target,
        ):
            while chunk := source.read(_CHUNK):
                target.write(chunk)

        dump_sql = workdir / "dump.sql"
        pgtools.run_tool(
            pg_restore,
            ["--no-owner", "--no-privileges", "--file", str(dump_sql), str(dump_path)],
            environment=environment,
            action="Reading the backup",
        )
        drop_sql = workdir / "drop.sql"
        drop_sql.write_text(_DROP_EXISTING_OBJECTS, encoding="utf-8")
        pgtools.run_tool(
            psql,
            [
                "--no-psqlrc",
                "--quiet",
                "--single-transaction",
                "--set",
                "ON_ERROR_STOP=1",
                "--file",
                str(drop_sql),
                "--file",
                str(dump_sql),
            ],
            environment=environment,
            action="The database restore",
        )

        if restore_settings:
            with zipfile.ZipFile(archive_path) as archive:
                if SETTINGS_NAME in archive.namelist():
                    paths.config_dir.mkdir(parents=True, exist_ok=True)
                    paths.user_settings_file.write_bytes(archive.read(SETTINGS_NAME))

    # Bring an older backup up to the current schema and built-in data.
    migrate.upgrade(url)

    referenced = asyncio.run(_raw_object_hashes(settings, paths))
    raw, raw_error = _restore_objects(archive_path, info, store, referenced)

    async def finish() -> str | None:
        db = Database.from_settings(settings, paths, application_name="omniosint-backup")
        try:
            async with db.session() as session:
                await seed_builtin(session)
                record(
                    session,
                    action="backup.restored",
                    actor=actor,
                    target_type="backup",
                    details={
                        "name": archive_path.name,
                        "backup_created_at": info.created_at,
                        "safety_backup": safety.path.name if safety else None,
                        "raw_responses": raw.to_dict(),
                        "raw_responses_error": raw_error,
                    },
                )
                await session.commit()
            return await migrate.current_revision(db.engine)
        finally:
            await db.dispose()

    revision = asyncio.run(finish())
    if raw_error is not None:
        raise OmniError(
            f"The database was restored, but the raw responses could not all be written "
            f"({raw_error}).",
            hint="Free disk space and restore the same archive again."
            + (f" The previous data is in {safety.path.name}." if safety else ""),
        )
    return RestoreResult(
        restored_from=info, safety_backup=safety, schema_revision=revision, raw=raw
    )


def parse_created_at(info: BackupInfo) -> datetime | None:
    try:
        return datetime.fromisoformat(info.created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
