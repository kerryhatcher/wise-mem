"""SQLModel table definitions.

Each `table=True` class is simultaneously a Pydantic model and a SQLAlchemy
table. The `*Create` / `*Read` classes are plain Pydantic models (no table)
used as FastAPI request/response schemas.
"""

from datetime import datetime, timezone
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Computed, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlmodel import Field, SQLModel

# Dimensionality of stored embeddings. Fixed in the column type, so changing it
# later requires a migration. 768 matches nomic-embed-text and many local models.
EMBEDDING_DIM = 768


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryBase(SQLModel):
    """Fields shared between the table and its create/read schemas."""

    content: str = Field(description="The remembered text / fact.")
    source: str | None = Field(
        default=None, description="Where this memory came from (agent, session, url)."
    )
    # Plain Pydantic dict here; the table model below overrides it with a JSONB column.
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary structured metadata (stored as JSONB).",
    )


class Memory(MemoryBase, table=True):
    """A single stored memory."""

    id: int | None = Field(default=None, primary_key=True)
    # Override `meta` to bind it to a real JSONB column.
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    # Nullable: a memory may be stored before it has been embedded.
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(EMBEDDING_DIM)),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    # Generated, read-only tsvector of `content` for full-text search. Postgres
    # keeps it in sync automatically; never written from Python. Excluded from
    # the API surface.
    content_tsv: Any | None = Field(
        default=None,
        exclude=True,
        sa_column=Column(
            TSVECTOR,
            Computed("to_tsvector('english', content)", persisted=True),
        ),
    )


class MemoryCreate(MemoryBase):
    """Request body for creating a memory."""

    embedding: list[float] | None = None


class MemoryUpdate(SQLModel):
    """Partial update — every field optional; unset fields are left unchanged."""

    content: str | None = None
    source: str | None = None
    meta: dict[str, Any] | None = None
    embedding: list[float] | None = None


class MemoryRead(MemoryBase):
    """Response model for returning a memory.

    Deliberately omits the raw `embedding` vector to keep payloads lean;
    embeddings are write/search-only via the API.
    """

    id: int
    created_at: datetime


class MemorySearchHit(MemoryRead):
    """A semantic search result: a memory plus its cosine distance (0 = closest)."""

    distance: float


class MemoryFullTextHit(MemoryRead):
    """A full-text search result: a memory plus its ts_rank score (higher = better)."""

    rank: float


class MemoryTextQuery(SQLModel):
    """Request body for text-driven search (semantic or full-text)."""

    query: str = Field(min_length=1, description="Natural-language search text.")
    limit: int = Field(default=5, ge=1, le=100)


class MemoryVectorQuery(SQLModel):
    """Request body for raw-vector similarity search."""

    embedding: list[float] = Field(description="Query vector to find neighbours of.")
    limit: int = Field(default=5, ge=1, le=100)


class MemoryHybridHit(MemoryRead):
    """A hybrid search result: a memory plus its fused RRF score (higher = better)."""

    score: float
