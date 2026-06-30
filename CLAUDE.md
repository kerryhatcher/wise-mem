# CLAUDE.md — wise-mem contributor guide

Guidance for AI agents (and humans) working on this repo. See
[`README.md`](./README.md) for what the project is and how to run it, and
[`tests/README.md`](./tests/README.md) for the test setup.

## Tooling

- **Python: always `uv`.** Run code with `uv run ...`; never bare
  `python`/`python3`/`pip`. Manage deps with `uv add` / `uv add --dev` /
  `uv remove`.
- **Lint with `ruff`** (`just lint`) and **format** (`just fmt`) before
  committing.
- **Tasks via `just`** — see the `justfile`. Common: `just test`, `just lint`,
  `just migrate`, `just revision "msg"`, `just serve`, `just cli ...`.
- **Conventional Commits**, small changesets, commit per task.

## Architecture rules

- **`service.py` is the parity seam.** Cross-cutting orchestration (project-link
  validation, auto/re-embedding, search dispatch) lives there and raises domain
  exceptions (`UnknownProjectsError`, `EmbeddingError`). **Both** `api.py` and
  `cli.py` must call `service.py` — never re-implement that logic in one
  entrypoint, or the API and CLI will drift. The API translates domain
  exceptions to HTTP status codes; the CLI to exit codes.
- **`crud.py` stays framework-free** (no FastAPI/Typer imports). It owns SQL.
- **Read models hide embeddings.** `MemoryRead` deliberately omits the raw
  `embedding` vector (write/search-only). Don't add it back to list/read
  responses.
- **The project filter is an `IN`-subquery, not a JOIN** (`crud._project_filter`)
  — a JOIN against the link table would fan out duplicate rows and corrupt
  ranking/`limit`.

## Schema & migrations

- **Alembic is the single source of truth.** `create_all` is not used;
  `run_migrations()` (`alembic upgrade head`) builds the schema, and the API
  runs it on startup. Add schema changes as migrations: `just revision "msg"`,
  then hand-write `upgrade()`/`downgrade()`.
- **Autogenerate can't handle the special columns** — the `pgvector` `vector`
  type, the generated `content_tsv` `tsvector`, and the HNSW/GIN index opclasses.
  Hand-write those with `op.execute(...)` / explicit `sa.Column(...)`.
- **`CREATE EXTENSION vector` needs a superuser** and is a one-time per-database
  step; the app role can't do it. The initial migration includes
  `CREATE EXTENSION IF NOT EXISTS vector`, which is a safe no-op once present.

## Embeddings

- Local **Ollama**, model `nomic-embed-text` (768-dim). `embeddings.py` applies
  the model's `search_document:` / `search_query:` task prefixes — keep using
  `embed_document` for stored text and `embed_query` for queries.
- `EMBEDDING_DIM` (768) is baked into the `vector(768)` column; changing it is a
  migration.
- pgvector returns embeddings as **numpy arrays** on read; treat
  `memory.embedding` accordingly.

## Async gotchas (these have bitten us)

- Use **SQLModel's** `AsyncSession` (`sqlmodel.ext.asyncio.session`) — it has
  `.exec()`. SQLAlchemy's `AsyncSession` only has `.execute()`.
- The session factory sets **`expire_on_commit=False`** so ORM attributes stay
  usable after commit (avoids lazy-load `MissingGreenlet` in async).
- `run_migrations()` runs `alembic upgrade` in a **worker thread** because
  Alembic's async `env.py` calls `asyncio.run`, which can't nest in a running
  loop.
- The CLI wraps each command in `asyncio.run(...)` and disposes the engine after.
- **Tests use `NullPool`** (`DB_NULLPOOL=true`) so connections aren't reused
  across event loops — that's what lets TestClient, CliRunner, and direct-async
  tests coexist.

## Behavior to preserve

- **`had_deleted_project`** is a sticky bool: flipped `False→True` only when a
  *project deletion* removes one of a memory's links (set in `crud.delete_project`
  **before** the cascade). Manual unlink must **not** set it.
- Memory↔project FKs are `ON DELETE CASCADE`; the many-to-many is managed with
  explicit link-table queries, not ORM lazy relationships.

## Testing

- `just test` runs pytest against a dedicated **`wisemem_test`** database
  (`conftest.py` rewrites the db name in `DATABASE_URL`) — tests never touch the
  real store. Requires Postgres+pgvector and a running Ollama.
- First-time bootstrap: `just test-db` (superuser creates the DB + extension).
- Tests are integration-first (real DB + real embedder); add coverage there
  rather than mocking the database.

## Secrets

`.env` is gitignored and holds `DATABASE_URL` (with the DB password). Never
commit credentials or echo them into committed files.
