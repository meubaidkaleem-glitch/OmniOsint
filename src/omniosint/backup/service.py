"""Backup and restore.

A backup is one zip archive holding a PostgreSQL custom-format dump, the user
settings file and a manifest with checksums. Secrets are not included: the
secret store is bound to the machine and account that created it.

Restore is atomic: the dump is converted to SQL and applied in a single
transaction together with the removal of the existing objects, so a failed
restore leaves the database exactly as it was.

Limitation (documented in SECURITY.md): archives are not encrypted in this
phase. Passphrase encryption arrives in Phase 13.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from alembic.script import ScriptDirectory

from omniosint import __version__
from omniosint.audit.service import CLI_ACTOR, Actor, record
from omniosint.backup import pgtools
from omniosint.core.config import Settings
from omniosint.core.errors import Conflict, OmniError, ValidationFailed
from omniosint.core.logging import get_logger
from omniosint.core.paths import AppPaths, restrict_to_owner
from omniosint.core.timeutil import isoformat, utcnow
from omniosint.database import migrate
from omniosint.database.engine import Database, build_database_url, ssl_mode_for
from omniosint.database.seeds import seed_builtin

log = get_logger(__name__)

FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"
DUMP_NAME = "database.dump"
SETTINGS_NAME = "config/settings.yaml"
_ARCHIVE_PREFIX = "omniosint-backup-"
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_CHUNK = 1024 * 1024

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
        }


@dataclass(frozen=True, slots=True)
class RestoreResult:
    restored_from: BackupInfo
    safety_backup: BackupInfo | None
    schema_revision: str | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


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


def create_backup(
    settings: Settings,
    paths: AppPaths,
    *,
    output_dir: Path | None = None,
    label: str | None = None,
    actor: Actor = CLI_ACTOR,
) -> BackupInfo:
    """Create a backup archive and return its description."""
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
        }
        partial = archive_path.with_suffix(".zip.partial")
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
                for member, source in members:
                    archive.write(source, arcname=member)
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
            {"name": archive_path.name, "size_bytes": info.size_bytes, "label": label},
        )
    )
    return info


def _read_manifest(archive: zipfile.ZipFile, path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    except (KeyError, ValueError, UnicodeDecodeError) as exc:
        raise BackupInvalid(f"{path.name} has no readable manifest.") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT_VERSION:
        raise BackupInvalid(f"{path.name} uses an unsupported backup format.")
    files = manifest.get("files")
    if not isinstance(files, list) or not any(
        isinstance(item, dict) and item.get("name") == DUMP_NAME for item in files
    ):
        raise BackupInvalid(f"{path.name} does not contain a database dump.")
    return manifest


def _info_from(path: Path, manifest: dict[str, Any]) -> BackupInfo:
    return BackupInfo(
        path=path,
        created_at=str(manifest.get("created_at", "")),
        app_version=str(manifest.get("app_version", "")),
        schema_revision=manifest.get("schema_revision"),
        server_version=str(manifest.get("server_version", "")),
        size_bytes=path.stat().st_size,
        label=manifest.get("label"),
        files=list(manifest["files"]),
    )


def verify_backup(path: Path) -> BackupInfo:
    """Check an archive's structure and checksums."""
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
                digest = hashlib.sha256()
                try:
                    with archive.open(member) as handle:
                        while chunk := handle.read(_CHUNK):
                            digest.update(chunk)
                except KeyError as exc:
                    raise BackupInvalid(f"{path.name} is missing {member}.") from exc
                if digest.hexdigest() != entry.get("sha256"):
                    raise BackupInvalid(
                        f"{path.name} failed its integrity check ({member} was modified)."
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


def restore_backup(
    settings: Settings,
    paths: AppPaths,
    archive_path: Path,
    *,
    safety_backup: bool = True,
    restore_settings: bool = False,
    actor: Actor = CLI_ACTOR,
) -> RestoreResult:
    """Replace the database content with a backup.

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
                    },
                )
                await session.commit()
            return await migrate.current_revision(db.engine)
        finally:
            await db.dispose()

    revision = asyncio.run(finish())
    return RestoreResult(restored_from=info, safety_backup=safety, schema_revision=revision)


def parse_created_at(info: BackupInfo) -> datetime | None:
    try:
        return datetime.fromisoformat(info.created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
