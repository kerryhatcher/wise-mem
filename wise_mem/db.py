"""Async database engine, session factory, and lifecycle helpers.

SQLModel sits on top of SQLAlchemy: we use SQLAlchemy's async engine and
`AsyncSession`, but query with SQLModel's `select()` and ORM models.
"""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem.config import settings

# Project root holds alembic.ini and the alembic/ script directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# A single engine per process owns the connection pool. Created once at import.
engine = create_async_engine(settings.database_url, echo=settings.db_echo)

# Session factory. expire_on_commit=False keeps attributes usable after commit,
# which matters for async code and for returning ORM objects from FastAPI routes.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a session, for use as a FastAPI dependency.

    Usage:
        @app.get("/memories")
        async def list_memories(session: AsyncSession = Depends(get_session)):
            ...
    """
    async with async_session_factory() as session:
        yield session


def alembic_config() -> Config:
    """Alembic config with absolute paths, so it works from any CWD."""
    cfg = Config(str(_PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PROJECT_ROOT / "alembic"))
    return cfg


async def run_migrations() -> None:
    """Bring the database schema up to head via Alembic.

    Alembic is the single source of truth for the schema. The first migration
    requires the `vector` extension to already exist (a superuser one-time step),
    after which its `CREATE EXTENSION IF NOT EXISTS` is a harmless no-op.

    Run in a worker thread: Alembic's async env.py calls `asyncio.run`, which
    cannot be nested inside an already-running event loop (e.g. the FastAPI
    lifespan). For multi-instance deployments, prefer running
    `alembic upgrade head` as a dedicated deploy step instead of on startup.
    """
    await asyncio.to_thread(command.upgrade, alembic_config(), "head")
