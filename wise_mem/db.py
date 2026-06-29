"""Async database engine, session factory, and lifecycle helpers.

SQLModel sits on top of SQLAlchemy: we use SQLAlchemy's async engine and
`AsyncSession`, but query with SQLModel's `select()` and ORM models.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem.config import settings

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


async def init_db() -> None:
    """Create all tables declared on SQLModel metadata.

    Fine for early development; switch to Alembic migrations once the schema
    needs to evolve without dropping data.
    """
    # Import models so their tables are registered on SQLModel.metadata before
    # create_all runs.
    from wise_mem import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
