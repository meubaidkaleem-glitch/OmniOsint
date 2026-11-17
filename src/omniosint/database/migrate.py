"""Schema migrations (Alembic), driven programmatically.

There is no ``alembic.ini``: the configuration is built in code so that the
database password never has to be written to a file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(url: URL | None = None) -> Config:
    config = Config()
    # configparser treats % as interpolation syntax.
    config.set_main_option("script_location", str(MIGRATIONS_DIR).replace("%", "%%"))
    if url is not None:
        config.attributes["sqlalchemy_url"] = url
    return config


def head_revision() -> str:
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise RuntimeError("No migrations are defined.")
    return head


def _current(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def current_revision(engine: AsyncEngine) -> str | None:
    """Revision the database is at, or ``None`` for an uninitialised database."""
    async with engine.connect() as connection:
        return await connection.run_sync(_current)


@dataclass(frozen=True, slots=True)
class SchemaState:
    current: str | None
    head: str

    @property
    def initialised(self) -> bool:
        return self.current is not None

    @property
    def up_to_date(self) -> bool:
        return self.current == self.head

    def describe(self) -> str:
        if not self.initialised:
            return "The database has no OmniOSINT schema yet."
        if self.up_to_date:
            return f"Schema is up to date (revision {self.current})."
        return f"Schema is at revision {self.current}; this version needs {self.head}."


async def schema_state(engine: AsyncEngine) -> SchemaState:
    return SchemaState(current=await current_revision(engine), head=head_revision())


def upgrade(url: URL, revision: str = "head") -> None:
    """Apply migrations. Must be called from synchronous code (it runs its own loop)."""
    command.upgrade(alembic_config(url), revision)


def downgrade(url: URL, revision: str) -> None:
    command.downgrade(alembic_config(url), revision)
