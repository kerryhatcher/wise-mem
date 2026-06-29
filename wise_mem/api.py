"""FastAPI application: CRUD + vector similarity search for memories."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem import crud
from wise_mem.db import get_session, init_db
from wise_mem.embeddings import EmbeddingError, embed_document, embed_query
from wise_mem.models import (
    MemoryCreate,
    MemoryFullTextHit,
    MemoryHybridHit,
    MemoryRead,
    MemorySearchHit,
    MemoryTextQuery,
    MemoryUpdate,
    MemoryVectorQuery,
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
    # Auto-embed the content unless the caller supplied a vector themselves.
    if data.embedding is None:
        try:
            data.embedding = await embed_document(data.content)
        except EmbeddingError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
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


def _semantic_hits(rows: list[tuple]) -> list[MemorySearchHit]:
    return [
        MemorySearchHit(**MemoryRead.model_validate(m).model_dump(), distance=dist)
        for m, dist in rows
    ]


@app.post("/memories/search", response_model=list[MemorySearchHit])
async def search_semantic(
    query: MemoryTextQuery, session: AsyncSession = Depends(get_session)
) -> list[MemorySearchHit]:
    """Semantic search: embed the query text, then cosine-nearest neighbours."""
    try:
        vector = await embed_query(query.query)
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    rows = await crud.search_memories(session, vector, limit=query.limit)
    return _semantic_hits(rows)


@app.post("/memories/search/vector", response_model=list[MemorySearchHit])
async def search_vector(
    query: MemoryVectorQuery, session: AsyncSession = Depends(get_session)
) -> list[MemorySearchHit]:
    """Similarity search from a pre-computed query vector."""
    rows = await crud.search_memories(session, query.embedding, limit=query.limit)
    return _semantic_hits(rows)


@app.post("/memories/search/fulltext", response_model=list[MemoryFullTextHit])
async def search_fulltext(
    query: MemoryTextQuery, session: AsyncSession = Depends(get_session)
) -> list[MemoryFullTextHit]:
    """Full-text keyword search over content, ranked by ts_rank."""
    rows = await crud.search_memories_fulltext(session, query.query, limit=query.limit)
    return [
        MemoryFullTextHit(**MemoryRead.model_validate(m).model_dump(), rank=rank)
        for m, rank in rows
    ]


@app.post("/memories/search/hybrid", response_model=list[MemoryHybridHit])
async def search_hybrid(
    query: MemoryTextQuery, session: AsyncSession = Depends(get_session)
) -> list[MemoryHybridHit]:
    """Hybrid search: fuse semantic and full-text results via RRF."""
    try:
        vector = await embed_query(query.query)
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    rows = await crud.search_memories_hybrid(
        session, embedding=vector, text=query.query, limit=query.limit
    )
    return [
        MemoryHybridHit(**MemoryRead.model_validate(m).model_dump(), score=score)
        for m, score in rows
    ]
