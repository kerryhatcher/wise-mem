"""Smoke test: init schema, insert a memory, read it back, clean up."""

import asyncio

from sqlmodel import delete, select

from wise_mem.db import async_session_factory, engine, init_db
from wise_mem.models import Memory


async def main() -> None:
    await init_db()
    print("✓ init_db: tables created")

    async with async_session_factory() as session:
        mem = Memory(content="wise-mem ORM is wired up", source="check_db", tags="setup")
        session.add(mem)
        await session.commit()
        await session.refresh(mem)
        print(f"✓ insert: id={mem.id} created_at={mem.created_at}")

        rows = (await session.exec(select(Memory))).all()
        print(f"✓ select: {len(rows)} row(s) -> {[r.content for r in rows]}")

        # tidy up so reruns stay clean
        await session.exec(delete(Memory).where(Memory.id == mem.id))
        await session.commit()
        print("✓ cleanup: test row deleted")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
