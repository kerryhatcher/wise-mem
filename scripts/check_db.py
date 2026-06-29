"""Smoke test: init schema, insert a memory with embedding + JSONB meta,
read it back (incl. a vector similarity query), clean up."""

import asyncio

from sqlmodel import delete, select

from wise_mem.db import async_session_factory, engine, run_migrations
from wise_mem.models import EMBEDDING_DIM, Memory


async def main() -> None:
    await run_migrations()
    print("✓ migrations: schema at head (table + HNSW + GIN)")

    # A toy 768-dim embedding (all 0.1) just to prove the round-trip.
    vec = [0.1] * EMBEDDING_DIM

    async with async_session_factory() as session:
        mem = Memory(
            content="wise-mem ORM is wired up",
            source="check_db",
            meta={"tags": ["setup", "smoke-test"], "confidence": 0.9},
            embedding=vec,
        )
        session.add(mem)
        await session.commit()
        await session.refresh(mem)
        print(f"✓ insert: id={mem.id} meta={mem.meta}")
        print(f"  embedding stored: {len(mem.embedding)} dims")

        # Vector similarity search: nearest neighbours to our query vector.
        rows = (
            await session.exec(
                select(Memory).order_by(Memory.embedding.cosine_distance(vec)).limit(5)
            )
        ).all()
        print(f"✓ similarity query: {len(rows)} row(s) -> {[r.content for r in rows]}")

        await session.exec(delete(Memory).where(Memory.id == mem.id))
        await session.commit()
        print("✓ cleanup: test row deleted")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
