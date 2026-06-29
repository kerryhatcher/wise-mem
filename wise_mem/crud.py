"""Async data-access functions for Memory records.

Routes call these; they own all the SQL. Keeping them framework-free means the
Typer CLI can reuse them without importing FastAPI.
"""

from sqlalchemy import func
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem.models import Memory, MemoryCreate, MemoryUpdate


async def create_memory(session: AsyncSession, data: MemoryCreate) -> Memory:
    memory = Memory.model_validate(data)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory


async def get_memory(session: AsyncSession, memory_id: int) -> Memory | None:
    return await session.get(Memory, memory_id)


async def list_memories(
    session: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[Memory]:
    stmt = select(Memory).order_by(Memory.created_at.desc()).offset(offset).limit(limit)
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


async def search_memories(
    session: AsyncSession, embedding: list[float], *, limit: int = 5
) -> list[tuple[Memory, float]]:
    """Return the `limit` nearest memories with their cosine distance.

    Only rows that have an embedding participate (NULL embeddings sort last and
    are excluded). Distance is in [0, 2]: 0 = identical direction.
    """
    distance = Memory.embedding.cosine_distance(embedding).label("distance")
    stmt = (
        select(Memory, distance)
        .where(Memory.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.exec(stmt)).all()
    return [(row[0], row[1]) for row in rows]


async def search_memories_fulltext(
    session: AsyncSession, query: str, *, limit: int = 5
) -> list[tuple[Memory, float]]:
    """Full-text keyword search over `content`, ranked by relevance.

    Uses `websearch_to_tsquery` so the query accepts human syntax (quoted
    phrases, `or`, `-exclude`). Matches against the generated `content_tsv`
    column, which is backed by a GIN index.
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank(Memory.content_tsv, tsquery).label("rank")
    stmt = (
        select(Memory, rank)
        .where(Memory.content_tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )
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
) -> list[tuple[Memory, float]]:
    """Combine vector and full-text results via Reciprocal Rank Fusion (RRF).

    Runs both the semantic (cosine) and full-text candidate searches, each
    capped at `pool` rows, then fuses them: a memory appearing at 1-based rank
    `r` in a list contributes `1 / (k + r)` to its fused score. Scores are
    summed across both lists, so a memory ranking well in either (or both)
    rises. Results are de-duplicated by memory id and the top `limit` are
    returned as `(Memory, fused_score)` tuples sorted by score descending.

    `k` damps the influence of lower ranks (the standard RRF constant is 60).
    """
    vector_rows = await search_memories(session, embedding, limit=pool)
    fulltext_rows = await search_memories_fulltext(session, text, limit=pool)

    scores: dict[int, float] = {}
    memories: dict[int, Memory] = {}
    for rows in (vector_rows, fulltext_rows):
        for rank_pos, (memory, _) in enumerate(rows, start=1):
            mem_id = memory.id
            scores[mem_id] = scores.get(mem_id, 0.0) + 1.0 / (k + rank_pos)
            memories.setdefault(mem_id, memory)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [(memories[mem_id], score) for mem_id, score in ranked[:limit]]
