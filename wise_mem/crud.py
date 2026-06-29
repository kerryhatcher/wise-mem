"""Async data-access functions for Memory records.

Routes call these; they own all the SQL. Keeping them framework-free means the
Typer CLI can reuse them without importing FastAPI.
"""

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
