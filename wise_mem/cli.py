"""Typer CLI at parity with the HTTP API.

Commands go through the same `service`/`crud` layer the API uses, so behaviour
(auto-embedding, re-embedding, project validation, search filters) is identical.
Structured results are emitted as JSON for easy scripting; actions print a short
confirmation. Schema is managed by Alembic (`wise-mem db upgrade`).
"""

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import typer

from wise_mem import crud, service
from wise_mem.db import alembic_config, async_session_factory, engine, run_migrations
from wise_mem.embeddings import EmbeddingError
from wise_mem.models import (
    Memory,
    MemoryCreate,
    MemoryRead,
    MemoryUpdate,
    Project,
    ProjectCreate,
    ProjectRead,
)

app = typer.Typer(help="wise-mem: a local memory and context store for agents.")
memory_app = typer.Typer(help="Create, search, and manage memories.")
project_app = typer.Typer(help="Create and manage projects.")
db_app = typer.Typer(help="Database schema (Alembic migrations).")
app.add_typer(memory_app, name="memory")
app.add_typer(project_app, name="project")
app.add_typer(db_app, name="db")

_SCORE_KEY = {
    "semantic": "distance",
    "vector": "distance",
    "fulltext": "rank",
    "hybrid": "score",
}


def _run(coro: Any) -> Any:
    """Run an async coroutine, disposing the engine's pool afterward.

    Disposal matters when several commands run in one process (tests): it stops
    a pooled asyncpg connection bound to one event loop being reused by the next.
    """

    async def _wrapped() -> Any:
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrapped())


def _error(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _memory_json(memory: Memory) -> dict[str, Any]:
    return MemoryRead.model_validate(memory).model_dump(mode="json")


def _project_json(project: Project) -> dict[str, Any]:
    return ProjectRead.model_validate(project).model_dump(mode="json")


def _emit(data: Any) -> None:
    typer.echo(json.dumps(data, indent=2))


def _parse_json_obj(raw: str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        _error(f"invalid JSON: {exc}")
    if not isinstance(value, dict):
        _error("--meta must be a JSON object")
    return value


# --- memory commands --------------------------------------------------------


@memory_app.command("add")
def memory_add(
    content: str = typer.Argument(..., help="The text to remember."),
    source: str | None = typer.Option(None, help="Where the memory came from."),
    meta: str | None = typer.Option(None, help="JSON object of metadata."),
    project: list[uuid.UUID] = typer.Option(
        [], "--project", "-p", help="Project UUID to link (repeatable)."
    ),
    embedding_file: Path | None = typer.Option(
        None, help="JSON array embedding; skips auto-embedding when given."
    ),
) -> None:
    """Create a memory (auto-embeds content unless --embedding-file is given)."""
    embedding = json.loads(embedding_file.read_text()) if embedding_file else None
    data = MemoryCreate(
        content=content,
        source=source,
        meta=_parse_json_obj(meta) or {},
        project_ids=list(project),
        embedding=embedding,
    )

    async def _do() -> Memory:
        async with async_session_factory() as session:
            return await service.create_memory(session, data)

    try:
        memory = _run(_do())
    except service.UnknownProjectsError as exc:
        _error(str(exc))
    except EmbeddingError as exc:
        _error(str(exc))
    _emit(_memory_json(memory))


@memory_app.command("get")
def memory_get(memory_id: int) -> None:
    """Fetch a single memory by id."""

    async def _do() -> Memory | None:
        async with async_session_factory() as session:
            return await crud.get_memory(session, memory_id)

    memory = _run(_do())
    if memory is None:
        _error(f"memory {memory_id} not found")
    _emit(_memory_json(memory))


@memory_app.command("list")
def memory_list(
    limit: int = typer.Option(50),
    offset: int = typer.Option(0),
    project: list[uuid.UUID] = typer.Option(
        [], "--project", "-p", help="Filter to memories in ANY of these projects."
    ),
) -> None:
    """List memories, newest first, optionally filtered by project."""

    async def _do() -> list[Memory]:
        async with async_session_factory() as session:
            return await crud.list_memories(
                session, limit=limit, offset=offset, project_ids=list(project) or None
            )

    memories = _run(_do())
    _emit([_memory_json(m) for m in memories])


@memory_app.command("update")
def memory_update(
    memory_id: int,
    content: str | None = typer.Option(None, help="New content (triggers re-embed)."),
    source: str | None = typer.Option(None),
    meta: str | None = typer.Option(None, help="JSON object; replaces stored meta."),
) -> None:
    """Partially update a memory; changing content re-embeds it."""
    fields: dict[str, Any] = {}
    if content is not None:
        fields["content"] = content
    if source is not None:
        fields["source"] = source
    if meta is not None:
        fields["meta"] = _parse_json_obj(meta)
    if not fields:
        _error("nothing to update (pass --content/--source/--meta)")
    data = MemoryUpdate(**fields)

    async def _do() -> Memory | None:
        async with async_session_factory() as session:
            memory = await crud.get_memory(session, memory_id)
            if memory is None:
                return None
            return await service.update_memory(session, memory, data)

    try:
        memory = _run(_do())
    except EmbeddingError as exc:
        _error(str(exc))
    if memory is None:
        _error(f"memory {memory_id} not found")
    _emit(_memory_json(memory))


@memory_app.command("delete")
def memory_delete(memory_id: int) -> None:
    """Delete a memory."""

    async def _do() -> bool:
        async with async_session_factory() as session:
            return await crud.delete_memory(session, memory_id)

    if not _run(_do()):
        _error(f"memory {memory_id} not found")
    typer.echo(f"deleted memory {memory_id}")


@memory_app.command("search")
def memory_search(
    query: str | None = typer.Argument(None, help="Search text (omit for --mode vector)."),
    mode: str = typer.Option("semantic", help="semantic|fulltext|hybrid|vector."),
    limit: int = typer.Option(5),
    project: list[uuid.UUID] = typer.Option(
        [], "--project", "-p", help="Filter to ANY of these projects."
    ),
    embedding_file: Path | None = typer.Option(
        None, help="JSON array query vector (required for --mode vector)."
    ),
) -> None:
    """Search memories by semantic, full-text, hybrid, or raw-vector mode."""
    if mode not in service.SEARCH_MODES:
        _error(f"--mode must be one of {', '.join(service.SEARCH_MODES)}")
    embedding = None
    if mode == "vector":
        if embedding_file is None:
            _error("--mode vector requires --embedding-file")
        embedding = json.loads(embedding_file.read_text())
    elif query is None:
        _error(f"--mode {mode} requires a query argument")

    async def _do() -> list[tuple[Memory, float]]:
        async with async_session_factory() as session:
            return await service.search(
                session,
                mode=mode,
                query=query,
                embedding=embedding,
                limit=limit,
                project_ids=list(project) or None,
            )

    try:
        rows = _run(_do())
    except EmbeddingError as exc:
        _error(str(exc))
    key = _SCORE_KEY[mode]
    _emit([{**_memory_json(m), key: score} for m, score in rows])


@memory_app.command("link")
def memory_link(memory_id: int, project_id: uuid.UUID) -> None:
    """Link a memory to a project."""

    async def _do() -> str:
        async with async_session_factory() as session:
            if await crud.get_memory(session, memory_id) is None:
                return "no_memory"
            if await crud.get_project(session, project_id) is None:
                return "no_project"
            await crud.link_memory_to_project(session, memory_id, project_id)
            return "ok"

    result = _run(_do())
    if result == "no_memory":
        _error(f"memory {memory_id} not found")
    if result == "no_project":
        _error(f"project {project_id} not found")
    typer.echo(f"linked memory {memory_id} -> project {project_id}")


@memory_app.command("unlink")
def memory_unlink(memory_id: int, project_id: uuid.UUID) -> None:
    """Remove a memory<->project link (does not set had_deleted_project)."""

    async def _do() -> bool:
        async with async_session_factory() as session:
            return await crud.unlink_memory_from_project(session, memory_id, project_id)

    if not _run(_do()):
        _error("link not found")
    typer.echo(f"unlinked memory {memory_id} from project {project_id}")


@memory_app.command("projects")
def memory_projects(memory_id: int) -> None:
    """List the projects a memory belongs to."""

    async def _do() -> list[Project] | None:
        async with async_session_factory() as session:
            if await crud.get_memory(session, memory_id) is None:
                return None
            return await crud.get_memory_projects(session, memory_id)

    projects = _run(_do())
    if projects is None:
        _error(f"memory {memory_id} not found")
    _emit([_project_json(p) for p in projects])


# --- project commands -------------------------------------------------------


@project_app.command("add")
def project_add(
    name: str = typer.Argument(..., help="Project name."),
    description: str | None = typer.Option(None),
) -> None:
    """Create a project; prints its generated UUID."""
    data = ProjectCreate(name=name, description=description)

    async def _do() -> Project:
        async with async_session_factory() as session:
            return await crud.create_project(session, data)

    _emit(_project_json(_run(_do())))


@project_app.command("list")
def project_list(
    limit: int = typer.Option(50), offset: int = typer.Option(0)
) -> None:
    """List projects, newest first."""

    async def _do() -> list[Project]:
        async with async_session_factory() as session:
            return await crud.list_projects(session, limit=limit, offset=offset)

    _emit([_project_json(p) for p in _run(_do())])


@project_app.command("get")
def project_get(project_id: uuid.UUID) -> None:
    """Fetch a project by UUID."""

    async def _do() -> Project | None:
        async with async_session_factory() as session:
            return await crud.get_project(session, project_id)

    project = _run(_do())
    if project is None:
        _error(f"project {project_id} not found")
    _emit(_project_json(project))


@project_app.command("delete")
def project_delete(project_id: uuid.UUID) -> None:
    """Delete a project; flags its memories and removes their links."""

    async def _do() -> bool:
        async with async_session_factory() as session:
            return await crud.delete_project(session, project_id)

    if not _run(_do()):
        _error(f"project {project_id} not found")
    typer.echo(f"deleted project {project_id}")


# --- db commands ------------------------------------------------------------


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Apply Alembic migrations to head."""
    _run(run_migrations())
    typer.echo("schema upgraded to head")


@db_app.command("current")
def db_current() -> None:
    """Print the current migration revision."""
    from alembic import command

    command.current(alembic_config())


if __name__ == "__main__":
    app()
