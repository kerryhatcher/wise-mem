"""End-to-end exercise of the hybrid (RRF) search endpoint against the real DB.

Seeds a few distinct memories, then calls POST /memories/search/hybrid and
asserts results carry a descending `score` and that a query matching both
semantically and lexically surfaces the right memory at the top.
Requires a running Ollama with nomic-embed-text. Cleans up created rows.
"""

from fastapi.testclient import TestClient

from wise_mem.api import app


def main() -> None:
    seed = [
        "Kerry prefers uv over pip for managing Python packages",
        "The wise-mem service stores agent memories in Postgres with pgvector",
        "Tailscale connects the thor server over a private network",
        "Reciprocal rank fusion blends vector and keyword search rankings",
    ]
    created_ids = []

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        print("✓ health")

        for text in seed:
            r = client.post(
                "/memories", json={"content": text, "source": "check_hybrid"}
            )
            assert r.status_code == 201, r.text
            created_ids.append(r.json()["id"])
        print(f"✓ create + auto-embed: {len(created_ids)} memories")

        # HYBRID: "postgres pgvector memory store" matches the storage memory both
        # lexically (postgres/pgvector) and semantically (memory store).
        r = client.post(
            "/memories/search/hybrid",
            json={"query": "postgres pgvector memory store", "limit": 4},
        )
        assert r.status_code == 200, r.text
        hits = r.json()
        assert hits, "hybrid returned no results"

        # Every hit has a float score field.
        assert all("score" in h and isinstance(h["score"], float) for h in hits)

        # Scores are ranked descending.
        scores = [h["score"] for h in hits]
        assert scores == sorted(scores, reverse=True), scores

        top = hits[0]
        print(
            f"✓ hybrid: top={top['content'][:45]!r} score={top['score']:.5f} "
            f"({len(hits)} hits)"
        )
        assert "Postgres" in top["content"], top["content"]
        print("✓ hybrid surfaces the dual-match memory at the top")
        print(f"✓ scores descending: {[round(s, 5) for s in scores]}")

        for mem_id in created_ids:
            assert client.delete(f"/memories/{mem_id}").status_code == 204
        print("✓ cleanup")

    print("\nAll hybrid checks passed.")


if __name__ == "__main__":
    main()
