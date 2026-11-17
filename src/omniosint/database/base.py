"""Declarative base shared by every model."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint names keep migrations reproducible across databases.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Fetch server-generated values (defaults and ``onupdate`` timestamps) as
    # part of the INSERT/UPDATE itself. Without this an updated row's
    # ``updated_at`` is left expired, and reading it later would need a lazy
    # load, which is not possible from async code.
    __mapper_args__ = {"eager_defaults": True}
