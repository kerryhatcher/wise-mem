"""Prove that PATCH /memories/{id} re-embeds when content changes.

Scenario:
  1. Create a memory with content A ("The cat sat on the mat").
  2. PATCH its content to a semantically very different B
     ("Quarterly financial revenue projections").
  3. Read the stored embedding straight from the DB and confirm it is now
     closer (cosine) to B than to A — i.e. it was recomputed, not left stale.
  4. PATCH a memory with an explicit embedding and confirm the route respects
     it instead of overwriting with a freshly computed one.

Everything runs on a single event loop (httpx ASGITransport against the app)
so the shared async engine's connections stay on one loop. Requires a running
Ollama with nomic-embed-text and the configured test DB.
"""

import asyncio
import math

import httpx

from wise_mem import crud
from wise_mem.api import app
from wise_mem.db import async_session_factory, run_migrations
from wise_mem.embeddings import embed_query
from wise_mem.models import EMBEDDING_DIM, Memory

CONTENT_A = "The cat sat on the mat"
CONTENT_B = "Quarterly financial revenue projections"

# A distinctive, deterministic vector the route must NOT overwrite.
EXPLICIT_EMBEDDING = [0.01 * ((i % 7) + 1) for i in range(EMBEDDING_DIM)]


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / (na * nb)


async def fetch_embedding(memory_id: int) -> list[float]:
    async with async_session_factory() as session:
        memory = await session.get(Memory, memory_id)
        return [float(x) for x in memory.embedding]


async def run() -> None:
    await run_migrations()  # apply schema (ASGITransport doesn't trigger lifespan)
    transport = httpx.ASGITransport(app=app)
    reembed_id = None
    explicit_id = None
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        try:
            # --- Re-embed-on-content-change case ----------------------------
            r = await client.post(
                "/memories", json={"content": CONTENT_A, "source": "check_reembed"}
            )
            assert r.status_code == 201, r.text
            reembed_id = r.json()["id"]
            print(f"✓ created memory {reembed_id} with content A")

            r = await client.patch(
                f"/memories/{reembed_id}", json={"content": CONTENT_B}
            )
            assert r.status_code == 200, r.text
            assert r.json()["content"] == CONTENT_B
            print(f"✓ patched memory {reembed_id} content -> B")

            stored = await fetch_embedding(reembed_id)
            emb_a = await embed_query(CONTENT_A)
            emb_b = await embed_query(CONTENT_B)
            dist_new = cosine_distance(stored, emb_b)
            dist_old = cosine_distance(stored, emb_a)
            print(f"  stored<->new('{CONTENT_B}') cosine distance = {dist_new:.4f}")
            print(f"  stored<->old('{CONTENT_A}') cosine distance = {dist_old:.4f}")
            assert dist_new < dist_old, (
                f"embedding looks stale: new={dist_new:.4f} not < old={dist_old:.4f}"
            )
            print("✓ embedding refreshed to match the NEW content")

            # --- Explicit-embedding-is-respected case -----------------------
            r = await client.post(
                "/memories", json={"content": CONTENT_A, "source": "check_reembed"}
            )
            assert r.status_code == 201, r.text
            explicit_id = r.json()["id"]
            r = await client.patch(
                f"/memories/{explicit_id}",
                json={"content": CONTENT_B, "embedding": EXPLICIT_EMBEDDING},
            )
            assert r.status_code == 200, r.text
            print(f"✓ patched memory {explicit_id} content B + explicit embedding")

            explicit_stored = await fetch_embedding(explicit_id)
            max_diff = max(
                abs(a - b)
                for a, b in zip(explicit_stored, EXPLICIT_EMBEDDING, strict=True)
            )
            print(f"  max |stored - supplied| = {max_diff:.2e}")
            assert max_diff < 1e-5, "explicit embedding was overwritten by re-embed"
            print("✓ explicit embedding on PATCH is respected (not overwritten)")
        finally:
            # CLEANUP — same loop, delete whatever was created.
            async with async_session_factory() as session:
                for mem_id in (reembed_id, explicit_id):
                    if mem_id is not None:
                        await crud.delete_memory(session, mem_id)
            print("✓ cleanup")

    print("\nAll re-embed checks passed.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
