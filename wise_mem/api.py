"""FastAPI application: CRUD + vector similarity search for memories."""

import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlmodel.ext.asyncio.session import AsyncSession

from wise_mem import crud, service
from wise_mem.db import get_session, run_migrations
from wise_mem.embeddings import EmbeddingError
from wise_mem.models import (
    MemoryCreate,
    MemoryFullTextHit,
    MemoryHybridHit,
    MemoryRead,
    MemorySearchHit,
    MemoryTextQuery,
    MemoryUpdate,
    MemoryVectorQuery,
    ProjectCreate,
    ProjectRead,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply Alembic migrations to head before serving requests.
    await run_migrations()
    yield


app = FastAPI(title="wise-mem", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/memories", response_model=MemoryRead, status_code=status.HTTP_201_CREATED)
async def create_memory(
    data: MemoryCreate, session: AsyncSession = Depends(get_session)
) -> MemoryRead:
    try:
        return await service.create_memory(session, data)
    except service.UnknownProjectsError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


@app.get("/memories", response_model=list[MemoryRead])
async def list_memories(
    limit: int = 50,
    offset: int = 0,
    project_ids: list[uuid.UUID] | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryRead]:
    return await crud.list_memories(
        session, limit=limit, offset=offset, project_ids=project_ids
    )


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
    try:
        return await service.update_memory(session, memory, data)
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc


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
        rows = await service.search(
            session,
            mode="semantic",
            query=query.query,
            limit=query.limit,
            project_ids=query.project_ids,
        )
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return _semantic_hits(rows)


@app.post("/memories/search/vector", response_model=list[MemorySearchHit])
async def search_vector(
    query: MemoryVectorQuery, session: AsyncSession = Depends(get_session)
) -> list[MemorySearchHit]:
    """Similarity search from a pre-computed query vector."""
    rows = await service.search(
        session,
        mode="vector",
        embedding=query.embedding,
        limit=query.limit,
        project_ids=query.project_ids,
    )
    return _semantic_hits(rows)


@app.post("/memories/search/fulltext", response_model=list[MemoryFullTextHit])
async def search_fulltext(
    query: MemoryTextQuery, session: AsyncSession = Depends(get_session)
) -> list[MemoryFullTextHit]:
    """Full-text keyword search over content, ranked by ts_rank."""
    rows = await service.search(
        session,
        mode="fulltext",
        query=query.query,
        limit=query.limit,
        project_ids=query.project_ids,
    )
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
        rows = await service.search(
            session,
            mode="hybrid",
            query=query.query,
            limit=query.limit,
            project_ids=query.project_ids,
        )
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return [
        MemoryHybridHit(**MemoryRead.model_validate(m).model_dump(), score=score)
        for m, score in rows
    ]


# --- Projects ---------------------------------------------------------------


@app.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate, session: AsyncSession = Depends(get_session)
) -> ProjectRead:
    return await crud.create_project(session, data)


@app.get("/projects", response_model=list[ProjectRead])
async def list_projects(
    limit: int = 50, offset: int = 0, session: AsyncSession = Depends(get_session)
) -> list[ProjectRead]:
    return await crud.list_projects(session, limit=limit, offset=offset)


@app.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProjectRead:
    project = await crud.get_project(session, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@app.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    deleted = await crud.delete_project(session, project_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")


# --- Memory <-> Project links -----------------------------------------------


@app.get("/memories/{memory_id}/projects", response_model=list[ProjectRead])
async def get_memory_projects(
    memory_id: int, session: AsyncSession = Depends(get_session)
) -> list[ProjectRead]:
    if await crud.get_memory(session, memory_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return await crud.get_memory_projects(session, memory_id)


@app.post(
    "/memories/{memory_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def link_memory_project(
    memory_id: int,
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    if await crud.get_memory(session, memory_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Memory not found")
    if await crud.get_project(session, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
    await crud.link_memory_to_project(session, memory_id, project_id)


@app.delete(
    "/memories/{memory_id}/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_memory_project(
    memory_id: int,
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    removed = await crud.unlink_memory_from_project(session, memory_id, project_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Link not found")
