"""Application service layer: orchestration shared by the API and the CLI.

These functions own the cross-cutting logic that sits above plain CRUD —
project-link validation, auto-embedding on create, re-embedding on content
change, and query embedding for search. They raise domain exceptions; callers
(FastAPI routes, Typer commands) translate those into HTTP responses or CLI
errors. Routing both entrypoints through here keeps them at parity by
construction.
"""

import uuid

from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem import crud
from wise_mem.embeddings import embed_document, embed_query
from wise_mem.models import Memory, MemoryCreate, MemoryUpdate

SEARCH_MODES = ("semantic", "vector", "fulltext", "hybrid")


class UnknownProjectsError(Exception):
    """Raised when a request references project IDs that don't exist."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Unknown project(s): {missing}")


async def _validate_projects(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> None:
    if not project_ids:
        return
    found = await crud.existing_project_ids(session, project_ids)
    missing = [str(p) for p in project_ids if p not in found]
    if missing:
        raise UnknownProjectsError(missing)


async def create_memory(session: AsyncSession, data: MemoryCreate) -> Memory:
    """Validate project links, auto-embed content if needed, then persist."""
    await _validate_projects(session, data.project_ids)
    if data.embedding is None:
        data.embedding = await embed_document(data.content)  # raises EmbeddingError
    return await crud.create_memory(session, data)


async def update_memory(
    session: AsyncSession, memory: Memory, data: MemoryUpdate
) -> Memory:
    """Apply a partial update, re-embedding when content changed.

    Skips re-embedding if the caller supplied their own embedding in the same
    request.
    """
    fields_set = data.model_fields_set
    if "content" in fields_set and "embedding" not in fields_set:
        data.embedding = await embed_document(data.content)  # raises EmbeddingError
    return await crud.update_memory(session, memory, data)


async def search(
    session: AsyncSession,
    *,
    mode: str,
    query: str | None = None,
    embedding: list[float] | None = None,
    limit: int = 5,
    project_ids: list[uuid.UUID] | None = None,
) -> list[tuple[Memory, float]]:
    """Dispatch a search by mode, embedding the query text where needed.

    Returns (Memory, score) tuples; the score's meaning depends on mode
    (cosine distance for semantic/vector, ts_rank for fulltext, fused RRF
    score for hybrid).
    """
    if mode == "semantic":
        vector = await embed_query(query)  # raises EmbeddingError
        return await crud.search_memories(
            session, vector, limit=limit, project_ids=project_ids
        )
    if mode == "vector":
        return await crud.search_memories(
            session, embedding, limit=limit, project_ids=project_ids
        )
    if mode == "fulltext":
        return await crud.search_memories_fulltext(
            session, query, limit=limit, project_ids=project_ids
        )
    if mode == "hybrid":
        vector = await embed_query(query)  # raises EmbeddingError
        return await crud.search_memories_hybrid(
            session,
            embedding=vector,
            text=query,
            limit=limit,
            project_ids=project_ids,
        )
    raise ValueError(f"unknown search mode: {mode!r}")
