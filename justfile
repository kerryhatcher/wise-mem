# wise-mem task runner. Run `just` (or `just --list`) to see recipes.

# Postgres host for provisioning the test DB without the containers.
# The container stack (`just up`) creates wisemem_test automatically, so you
# normally don't need `test-db`. Override per-invocation: `just pg_host=thor... test-db`.
pg_host := "localhost"
pg_port := "5433"
pg_superuser := "wise-mem"
db_role := "wise-mem"
test_db := "wisemem_test"

# List available recipes.
default:
    @just --list

# Sync dependencies (including the dev group).
sync:
    uv sync

# --- Local container stack (Postgres + Memgraph) ---------------------------

# Start the local Postgres + Memgraph containers (detached).
up:
    docker compose up -d

# Stop the containers (data is kept in named volumes).
down:
    docker compose down

# Stop and DELETE all container data — fresh databases on the next `just up`.
reset:
    docker compose down -v

# Tail container logs: `just logs` or `just logs postgres`.
logs *args:
    docker compose logs -f {{args}}

# Show container status.
ps:
    docker compose ps

# psql shell into the Postgres container.
db-shell:
    docker compose exec postgres psql -U wise-mem -d wise-mem

# mgconsole (Cypher) shell into the Memgraph container.
mg-shell:
    docker compose exec memgraph mgconsole

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

# Create test DB + pgvector (only for a non-container Postgres; `just up` does it).
test-db:
    psql -h {{pg_host}} -p {{pg_port}} -U {{pg_superuser}} -c 'CREATE DATABASE "{{test_db}}" OWNER "{{db_role}}";' || true
    psql -h {{pg_host}} -p {{pg_port}} -U {{pg_superuser}} -d {{test_db}} -c 'CREATE EXTENSION IF NOT EXISTS vector;'

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
