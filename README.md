# wise-mem

A local memory and context store for AI agents. It stores text "memories" in
Postgres and makes them retrievable by **semantic similarity** (vector search),
**full-text keywords**, or a **hybrid** of both — with optional scoping to
**projects**. It exposes the same capabilities over an HTTP API and a CLI.

## Features

- **Memories** with arbitrary JSONB metadata, served write/search-only embeddings.
- **Auto-embedding** on create and **re-embedding** when content changes, via a
  local [Ollama](https://ollama.com) model (`nomic-embed-text`, 768-dim).
- **Four search modes**
  - *semantic* — cosine similarity over `pgvector` (HNSW index)
  - *full-text* — Postgres `tsvector`/`websearch_to_tsquery` (GIN index)
  - *hybrid* — Reciprocal Rank Fusion (RRF) of semantic + full-text
  - *vector* — search from a pre-computed query vector
- **Projects** keyed by UUID; memories link to one or more projects
  (many-to-many) and every search/list can be filtered to a set of projects
  (match ANY). Deleting a project keeps its memories but flags them
  (`had_deleted_project`).
- **API and CLI at parity**, sharing one service layer.
- **Alembic-managed schema** as the single source of truth.

## Stack

Python 3.13 · FastAPI · SQLModel · async SQLAlchemy + asyncpg · PostgreSQL +
pgvector · Alembic · Typer + Rich · Ollama · managed with `uv`, linted with
`ruff`, tasks via `just`.

## Layout

```
wise_mem/
  config.py       # pydantic-settings (DATABASE_URL, OLLAMA_HOST, ...)
  db.py           # async engine, session factory, Alembic-backed run_migrations()
  models.py       # SQLModel tables + API schemas
  crud.py         # framework-free async data access
  service.py      # shared orchestration (validation, embedding, search dispatch)
  embeddings.py   # Ollama client (nomic-embed-text task prefixes)
  api.py          # FastAPI app
  cli.py          # Typer CLI (`wise-mem`)
alembic/          # migrations (the schema source of truth)
tests/            # pytest suite (see tests/README.md)
justfile          # common tasks
```

`crud.py` owns SQL and stays framework-free; `service.py` adds the cross-cutting
logic (project validation, auto/re-embedding, search dispatch) and raises domain
exceptions. Both `api.py` and `cli.py` call `service.py`, so they cannot drift.

## Prerequisites

- **uv** for dependency management.
- **Ollama** running with the embedding model: `ollama pull nomic-embed-text`.
- **PostgreSQL** with **pgvector** — either the local container stack below
  (recommended) or an existing server with the `pgvector` package installed and
  `CREATE EXTENSION vector` run once per database by a superuser.
- **Docker** (only for the container stack).

## Setup

Install dependencies first:

```bash
just sync          # uv sync
```

**Option A — local container stack (recommended).** Brings up Postgres
(pgvector ≥ 0.8) and Memgraph; the Postgres init script creates both the app DB
and `wisemem_test` with the extension:

```bash
cp .env.example .env     # defaults point at the containers (localhost:5433)
just up                  # start postgres + memgraph (docker compose up -d)
just migrate             # apply the schema (uv run alembic upgrade head)
```

`just down` stops them (data kept); `just reset` wipes the volumes. The Memgraph
container is for the Phase 2 graph projection (see `docs/roadmap.md`); it's
started now so it's ready, but nothing reads it yet.

**Option B — existing Postgres.** Create a `.env` (gitignored) — note the
`+asyncpg` driver — pointing at your server, then migrate:

```dotenv
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/wise-mem
OLLAMA_HOST=http://localhost:11434
EMBEDDING_MODEL=nomic-embed-text
# DB_ECHO=false
```

```bash
just migrate       # uv run alembic upgrade head
```

The API also applies migrations on startup, so a fresh database self-migrates
the first time it serves a request.

## Running the API

```bash
just serve                       # uvicorn wise_mem.api:app --reload
# interactive docs at http://127.0.0.1:8000/docs
```

Key endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/memories` | create (auto-embeds; accepts `project_ids`) |
| `GET` | `/memories` | list (`?project_ids=` filter) |
| `GET`/`PATCH`/`DELETE` | `/memories/{id}` | fetch / partial update (re-embeds) / delete |
| `POST` | `/memories/search` | semantic (text) |
| `POST` | `/memories/search/{vector,fulltext,hybrid}` | other modes |
| `POST`/`DELETE` | `/memories/{id}/projects/{project_id}` | link / unlink |
| `GET` | `/memories/{id}/projects` | a memory's projects |
| `POST`/`GET`/`DELETE` | `/projects` , `/projects/{id}` | project CRUD |

## Using the CLI

The `wise-mem` command mirrors the API. Output is human-friendly tables by
default; pass `--json` for scripting.

```bash
just cli project add "My Project"
just cli memory add "Kerry prefers uv over pip" --project <project-uuid>
just cli memory search "python package manager"            # semantic
just cli memory search "postgres" --mode fulltext
just cli -- --json memory list --project <project-uuid>    # JSON for scripts
just cli db current
```

(Outside `just`, invoke as `uv run wise-mem ...`.)

## Development

```bash
just lint            # ruff check
just fmt             # ruff format
just test            # pytest  (see tests/README.md for the test-db bootstrap)
just check           # lint + test
just revision "msg"  # new Alembic migration
```

Schema changes are **always** Alembic migrations — `create_all` is not used.
pgvector/`tsvector`/generated columns aren't handled by autogenerate, so
hand-write those parts of a migration. See `CLAUDE.md` for contributor
conventions.

## License

See [LICENSE](./LICENSE).
