"""Database engine/session for the Peakstone API.

Dev defaults to SQLite (zero infra); production uses Postgres via PEAKSTONE_DATABASE_URL
(see infra/docker-compose.yml). JSON columns become JSONB on Postgres.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("PEAKSTONE_DATABASE_URL", "sqlite:///./peakstone.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create tables if missing (dev convenience; production uses Alembic migrations)."""
    from . import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a session, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
