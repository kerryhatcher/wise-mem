"""Direct tests of the shared service/crud layer."""

import uuid

import pytest

from wise_mem import crud, service
from wise_mem.db import async_session_factory
from wise_mem.models import MemoryCreate, ProjectCreate


def test_create_with_unknown_project_raises(run):
    async def _t():
        async with async_session_factory() as session:
            with pytest.raises(service.UnknownProjectsError):
                await service.create_memory(
                    session,
                    MemoryCreate(content="x", project_ids=[uuid.uuid4()]),
                )

    run(_t())


def test_search_modes_return_results(run):
    async def _t():
        async with async_session_factory() as session:
            await service.create_memory(session, MemoryCreate(content="alpha beta"))
            for mode in ("semantic", "fulltext", "hybrid"):
                rows = await service.search(
                    session, mode=mode, query="alpha", limit=5
                )
                assert rows, f"{mode} returned nothing"

    run(_t())


def test_link_then_unlink(run):
    async def _t():
        async with async_session_factory() as session:
            project = await crud.create_project(session, ProjectCreate(name="P"))
            memory = await service.create_memory(session, MemoryCreate(content="m"))
            await crud.link_memory_to_project(session, memory.id, project.id)
            projects = await crud.get_memory_projects(session, memory.id)
            assert [p.id for p in projects] == [project.id]
            assert await crud.unlink_memory_from_project(
                session, memory.id, project.id
            )
            assert await crud.get_memory_projects(session, memory.id) == []

    run(_t())
