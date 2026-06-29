"""SQLModel table definitions.

Each class is simultaneously a Pydantic model and a SQLAlchemy table
(`table=True`). The `*Create` / `*Read` classes are plain Pydantic models that
share the base fields but are not tables — use them as FastAPI request/response
schemas so you never expose the raw table model directly.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryBase(SQLModel):
    """Fields shared between the table and its create/read schemas."""

    content: str = Field(description="The remembered text / fact.")
    source: str | None = Field(
        default=None, description="Where this memory came from (agent, session, url)."
    )
    tags: str | None = Field(
        default=None, description="Comma-separated tags for simple filtering."
    )


class Memory(MemoryBase, table=True):
    """A single stored memory."""

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )


class MemoryCreate(MemoryBase):
    """Request body for creating a memory."""


class MemoryRead(MemoryBase):
    """Response model for returning a memory."""

    id: int
    created_at: datetime
