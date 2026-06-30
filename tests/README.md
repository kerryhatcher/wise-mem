# Tests

The suite is integration-first: it runs against a **real Postgres** (with
`pgvector`) and a **real Ollama** (for embeddings), exercising the app the way
it actually runs. There are no mocks for the database or the embedder.

## What it covers

| File | Area |
| --- | --- |
| `test_memories.py` | memory CRUD, auto-embed on create, re-embed on content change, explicit-embedding preservation, `meta` replace |
| `test_search.py` | semantic, full-text (incl. `websearch` exclusion), hybrid (RRF), and raw-vector search |
| `test_projects.py` | project CRUD, linking, the ANY-of project filter, unlink-vs-delete flag semantics, cascade, 404s |
| `test_service.py` | the shared `service`/`crud` layer directly |
| `test_cli.py` | Typer CLI parity (via `--json`) and human table rendering |

## Prerequisites

1. **Postgres reachable** at the host in your `DATABASE_URL` (see `.env`), with
   the `wise-mem` login role already created.
2. **The `pgvector` server package installed** on that Postgres host
   (`postgresql-<major>-pgvector`). Installing the extension into a database
   needs a **superuser** — the app role can't do it itself.
3. **Ollama running** with the `nomic-embed-text` model pulled
   (`ollama pull nomic-embed-text`), reachable at `OLLAMA_HOST`
   (default `http://localhost:11434`). Tests create memories, which auto-embed.
4. **The `wisemem_test` database**, provisioned once (below).

## One-time bootstrap

The tests never touch your real database: `conftest.py` reads `DATABASE_URL`
(from the environment or `.env`) and **rewrites the database name** to
`wisemem_test`. You must create that database and enable `pgvector` in it once,
as a superuser:

```bash
just test-db
# equivalently:
psql -h <host> -U postgres -c 'CREATE DATABASE "wisemem_test" OWNER "wise-mem";'
psql -h <host> -U postgres -d wisemem_test -c 'CREATE EXTENSION IF NOT EXISTS vector;'
```

The schema itself is created automatically — a session-scoped fixture runs
`alembic upgrade head` before the first test.

## Running

```bash
just test            # uv run pytest
just test -k cli     # pass through pytest args
uv run pytest        # directly
```

## How isolation works

- **Dedicated database.** The db name in `DATABASE_URL` is swapped to
  `wisemem_test` in `conftest.py` *before* `wise_mem` is imported (the engine is
  built at import time), so the production store is never written to.
- **NullPool engine.** `DB_NULLPOOL=true` is set for tests so connections are
  not pooled. This lets `TestClient` (its own event loop), `CliRunner`
  (`asyncio.run` per command), and direct-async tests share one engine without
  a connection bound to a closed loop being reused — the usual async-test
  failure mode.
- **Truncate between tests.** An autouse fixture runs
  `TRUNCATE memory, project, memory_project RESTART IDENTITY CASCADE` before
  each test, so every test starts from an empty, sequence-reset schema.

## CI note

For a fresh Postgres (e.g. a CI service container), provision before running:
create the `wise-mem` role, the `wisemem_test` database, and
`CREATE EXTENSION vector` (superuser), then point `DATABASE_URL` at that server.
Ollama with `nomic-embed-text` must also be available, or the embedding-backed
tests will fail with a 503/`EmbeddingError`.
