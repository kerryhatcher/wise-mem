"""FastAPI application: CRUD + vector similarity search for memories."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem import crud
from wise_mem.db import get_session, init_db
from wise_mem.models import (
    MemoryCreate,
    MemoryRead,
    MemorySearchHit,
    MemorySearchQuery,
    MemoryUpdate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure extension, table, and index exist before serving requests.
    await init_db()
    yield


app = FastAPI(title="wise-mem", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/memories", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    data: MemoryCreate, session: AsyncSession = Depends(get_session)
) -> MemoryRead:
    return await crud.create_memory(session, data)


@app.get("/memories", response_model=list[MemoryRead])
async def list_memories(
    limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_session)
) -> list[MemoryRead]:
    return await crud.list_memories(session, limit=limit, offset=offset)


@app.get("/memories/{memory_id}", response_model=MemoryRead)
async def get_memory(
    memory_id: int, session: AsyncSession = Depends(get_session)
) -> MemoryRead:
    memory = await crud.get_memory(session, memory_id)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return memory


@app.patch("/memories/{memory_id}", response_model=MemoryRead)
async def update_memory(
    memory_id: int,
    data: MemoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> MemoryRead:
    memory = await crud.get_memory(session, memory_id)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return await crud.update_memory(session, memory, data)


@app.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: int, session: AsyncSession = Depends(get_session)
) -> None:
    deleted = await crud.delete_memory(session, memory_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")


@app.post("/memories/search", response_model=list[MemorySearchHit])
async def search_memories(
    query: MemorySearchQuery, session: AsyncSession = Depends(get_session)
) -> list[MemorySearchHit]:
    hits = await crud.search_memories(session, query.embedding, limit=query.limit)
    return [
        MemorySearchHit(**MemoryRead.model_validate(memory).model_dump(), distance=dist)
        for memory, dist in hits
    ]
