# wise-mem task runner. Run `just` (or `just --list`) to see recipes.

# Postgres connection used only for provisioning the test database.
# Override per-invocation, e.g. `just pg_host=localhost test-db`.
pg_host := "thor.tailb56d83.ts.net"
pg_superuser := "postgres"
db_role := "wise-mem"
test_db := "wisemem_test"

# List available recipes.
default:
    @just --list

# Sync dependencies (including the dev group).
sync:
    uv sync

# Lint with ruff.
lint:
    uvx ruff check wise_mem/ tests/ alembic/

# Auto-format with ruff.
fmt:
    uvx ruff format wise_mem/ tests/ alembic/

# Run the test suite (pass extra pytest args, e.g. `just test -k cli`).
test *args:
    uv run pytest {{args}}

# Lint then test.
check: lint test

# Create the test database + pgvector extension (one-time, superuser; see tests/README.md).
test-db:
    psql -h {{pg_host}} -U {{pg_superuser}} -c 'CREATE DATABASE "{{test_db}}" OWNER "{{db_role}}";' || true
    psql -h {{pg_host}} -U {{pg_superuser}} -d {{test_db}} -c 'CREATE EXTENSION IF NOT EXISTS vector;'

# Apply Alembic migrations to the database in .env.
migrate:
    uv run alembic upgrade head

# Show the current migration revision.
db-current:
    uv run alembic current

# Create a new migration: `just revision "add widget table"`.
revision message:
    uv run alembic revision -m "{{message}}"

# Run the API with autoreload.
serve host="127.0.0.1" port="8000":
    uv run uvicorn wise_mem.api:app --reload --host {{host}} --port {{port}}

# Run the CLI: `just cli memory list` or `just cli -- --json project list`.
cli *args:
    uv run wise-mem {{args}}
