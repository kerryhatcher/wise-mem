-- Postgres first-init script (runs once, on an empty data directory, as the
-- superuser POSTGRES_USER). Mounted at /docker-entrypoint-initdb.d.
--
-- 1. Enable pgvector in the primary database (`wise-mem`). Alembic's initial
--    migration also does `CREATE EXTENSION IF NOT EXISTS vector`, so this is
--    belt-and-suspenders, but it lets non-migration tooling work immediately.
-- 2. Create the dedicated test database. conftest.py rewrites the DATABASE_URL
--    db name to `wisemem_test`, so the suite never touches the real store.
--    (Re-running is not a concern: initdb scripts only run on a fresh volume.)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE DATABASE wisemem_test OWNER "wise-mem";

\connect wisemem_test
CREATE EXTENSION IF NOT EXISTS vector;
