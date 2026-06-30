"""Shared pytest fixtures.

Tests run against a dedicated `wisemem_test` database (the real DATABASE_URL's
db name is swapped out, so the production store is never touched) with a
non-pooling engine. The test DB and its `vector` extension are provisioned out
of band (a superuser one-time step).
"""

import os
import re
from pathlib import Path


def _derive_test_url() -> str:
    base = os.environ.get("DATABASE_URL")
    if not base:
        env_file = Path(__file__).resolve().parents[1] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("DATABASE_URL="):
                    base = line.split("=", 1)[1].strip()
                    break
    if not base:
        raise RuntimeError("DATABASE_URL not set and not found in .env")
    # Swap the database name -> never run tests against the real database.
    return re.sub(r"/[^/]+$", "/wisemem_test", base)


# Must happen before importing wise_mem (settings/engine read env at import).
os.environ["DATABASE_URL"] = _derive_test_url()
os.environ["DB_NULLPOOL"] = "true"

import asyncio  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from wise_mem.api import app  # noqa: E402
from wise_mem.cli import app as cli_app  # noqa: E402
from wise_mem.db import async_session_factory, run_migrations  # noqa: E402


def _run(coro):
    """Run a coroutine on a fresh event loop (NullPool => no cross-loop reuse)."""
    return asyncio.run(coro)


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    _run(run_migrations())
    yield


@pytest.fixture(autouse=True)
def _clean_db():
    async def _truncate():
        async with async_session_factory() as session:
            await session.exec(
                text("TRUNCATE memory, project, memory_project RESTART IDENTITY CASCADE")
            )
            await session.commit()

    _run(_truncate())
    yield


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def cli():
    return cli_app


@pytest.fixture
def run():
    """Expose the coroutine runner for direct crud/service tests."""
    return _run
