"""Async data-access functions for Memory and Project records.

Routes call these; they own all the SQL. Keeping them framework-free means the
Typer CLI can reuse them without importing FastAPI. The memory<->project
many-to-many is managed with explicit link-table queries (not ORM lazy
relationships) to stay safe under async SQLAlchemy.
"""

import uuid

from sqlalchemy import func, update
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem.models import (
    Memory,
    MemoryCreate,
    MemoryProjectLink,
    MemoryUpdate,
    Project,
    ProjectCreate,
)


def _project_filter(project_ids: list[uuid.UUID]):
    """A WHERE predicate: memory is linked to ANY of `project_ids`."""
    return Memory.id.in_(
        select(MemoryProjectLink.memory_id).where(
            MemoryProjectLink.project_id.in_(project_ids)
        )
    )


# --- Memory CRUD ------------------------------------------------------------


async def create_memory(session: AsyncSession, data: MemoryCreate) -> Memory:
    memory = Memory.model_validate(data)  # extra project_ids field is ignored
    session.add(memory)
    await session.flush()  # assign memory.id before linking
    for project_id in data.project_ids:
        session.add(MemoryProjectLink(memory_id=memory.id, project_id=project_id))
    await session.commit()
    await session.refresh(memory)
    return memory


async def get_memory(session: AsyncSession, memory_id: int) -> Memory | None:
    return await session.get(Memory, memory_id)


async def list_memories(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    project_ids: list[uuid.UUID] | None = None,
) -> list[Memory]:
    stmt = select(Memory)
    if project_ids:
        stmt = stmt.where(_project_filter(project_ids))
    stmt = stmt.order_by(Memory.created_at.desc()).offset(offset).limit(limit)
    return list((await session.exec(stmt)).all())


async def update_memory(
    session: AsyncSession, memory: Memory, data: MemoryUpdate
) -> Memory:
    # exclude_unset: only fields the client actually sent are applied. A sent
    # `meta` REPLACES the stored dict wholesale (standard PATCH semantics), it
    # does not deep-merge keys.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(memory, field, value)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def delete_memory(session: AsyncSession, memory_id: int) -> bool:
    result = await session.exec(delete(Memory).where(Memory.id == memory_id))
    await session.commit()
    return result.rowcount > 0


# --- Search (all accept an optional ANY-of project filter) ------------------


async def search_memories(
    session: AsyncSession,
    embedding: list[float],
    *,
    limit: int = 5,
    project_ids: list[uuid.UUID] | None = None,
) -> list[tuple[Memory, float]]:
    """Return the `limit` nearest memories with their cosine distance.

    Only rows that have an embedding participate. Distance is in [0, 2].
    """
    distance = Memory.embedding.cosine_distance(embedding).label("distance")
    stmt = select(Memory, distance).where(Memory.embedding.is_not(None))
    if project_ids:
        stmt = stmt.where(_project_filter(project_ids))
    stmt = stmt.order_by(distance).limit(limit)
    rows = (await session.exec(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def search_memories_fulltext(
    session: AsyncSession,
    query: str,
    *,
    limit: int = 5,
    project_ids: list[uuid.UUID] | None = None,
) -> list[tuple[Memory, float]]:
    """Full-text keyword search over `content`, ranked by relevance.

    Uses `websearch_to_tsquery` so the query accepts human syntax (quoted
    phrases, `or`, `-exclude`). Matches the GIN-indexed `content_tsv` column.
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank(Memory.content_tsv, tsquery).label("rank")
    stmt = select(Memory, rank).where(Memory.content_tsv.op("@@")(tsquery))
    if project_ids:
        stmt = stmt.where(_project_filter(project_ids))
    stmt = stmt.order_by(rank.desc()).limit(limit)
    rows = (await session.exec(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def search_memories_hybrid(
    session: AsyncSession,
    *,
    embedding: list[float],
    text: str,
    limit: int = 5,
    k: int = 60,
    pool: int = 50,
    project_ids: list[uuid.UUID] | None = None,
) -> list[tuple[Memory, float]]:
    """Combine vector and full-text results via Reciprocal Rank Fusion (RRF).

    Runs both candidate searches (each capped at `pool`, each honouring the
    project filter), then fuses: a memory at 1-based rank `r` in a list
    contributes `1 / (k + r)`, summed across both lists. De-duplicated by id,
    top `limit` returned as `(Memory, fused_score)` sorted descending.
    """
    vector_rows = await search_memories(
        session, embedding, limit=pool, project_ids=project_ids
    )
    fulltext_rows = await search_memories_fulltext(
        session, text, limit=pool, project_ids=project_ids
    )

    scores: dict[int, float] = {}
    memories: dict[int, Memory] = {}
    for rows in (vector_rows, fulltext_rows):
        for rank_pos, (memory, _) in enumerate(rows, start=1):
            mem_id = memory.id
            scores[mem_id] = scores.get(mem_id, 0.0) + 1.0 / (k + rank_pos)
            memories.setdefault(mem_id, memory)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(memories[mem_id], score) for mem_id, score in ranked[:limit]]


# --- Project CRUD -----------------------------------------------------------


async def create_project(session: AsyncSession, data: ProjectCreate) -> Project:
    project = Project.model_validate(data)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def get_project(session: AsyncSession, project_id: uuid.UUID) -> Project | None:
    return await session.get(Project, project_id)


async def list_projects(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[Project]:
    stmt = (
        select(Project).order_by(Project.created_at.desc()).offset(offset).limit(limit)
    )
    return list((await session.exec(stmt)).all())


async def existing_project_ids(
    session: AsyncSession, project_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Return the subset of `project_ids` that actually exist."""
    if not project_ids:
        return set()
    stmt = select(Project.id).where(Project.id.in_(project_ids))
    return set((await session.exec(stmt)).all())


async def delete_project(session: AsyncSession, project_id: uuid.UUID) -> bool:
    project = await session.get(Project, project_id)
    if project is None:
        return False
    # Flag every memory currently linked to this project BEFORE the links are
    # removed (the cascade fires when the project is deleted). Sticky: only
    # flips False -> True.
    await session.exec(
        update(Memory)
        .where(
            Memory.id.in_(
                select(MemoryProjectLink.memory_id).where(
                    MemoryProjectLink.project_id == project_id
                )
            )
        )
        .values(had_deleted_project=True)
    )
    await session.delete(project)  # memory_project rows cascade away
    await session.commit()
    return True


# --- Memory <-> Project links -----------------------------------------------


async def link_memory_to_project(
    session: AsyncSession, memory_id: int, project_id: uuid.UUID
) -> None:
    """Idempotently link a memory to a project."""
    existing = await session.get(MemoryProjectLink, (memory_id, project_id))
    if existing is None:
        session.add(MemoryProjectLink(memory_id=memory_id, project_id=project_id))
        await session.commit()


async def unlink_memory_from_project(
    session: AsyncSession, memory_id: int, project_id: uuid.UUID
) -> bool:
    """Remove a link. Does NOT set had_deleted_project (intentional detach)."""
    result = await session.exec(
        delete(MemoryProjectLink).where(
            MemoryProjectLink.memory_id == memory_id,
            MemoryProjectLink.project_id == project_id,
        )
    )
    await session.commit()
    return result.rowcount > 0


async def get_memory_projects(
    session: AsyncSession, memory_id: int
) -> list[Project]:
    stmt = (
        select(Project)
        .join(MemoryProjectLink, MemoryProjectLink.project_id == Project.id)
        .where(MemoryProjectLink.memory_id == memory_id)
        .order_by(Project.created_at.desc())
    )
    return list((await session.exec(stmt)).all())
