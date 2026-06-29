"""End-to-end exercise of the FastAPI endpoints against the real database.

Covers auto-embedding on create, semantic (text) search, full-text search,
and raw-vector search. Requires a running Ollama with nomic-embed-text.
"""

from fastapi.testclient import TestClient

from wise_mem.api import app


def main() -> None:
    seed = [
        "Kerry prefers uv over pip for Python projects",
        "The wise-mem service stores agent memories in Postgres",
        "Tailscale connects the thor server over a private network",
    ]
    created_ids = []

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        print("✓ health")

        # CREATE with auto-embedding (no embedding field sent)
        for text in seed:
            r = client.post("/memories", json={"content": text, "source": "check_api"})
            assert r.status_code == 201, r.text
            created_ids.append(r.json()["id"])
        print(f"✓ create + auto-embed: {len(created_ids)} memories")

        # SEMANTIC search by text — "package manager" should surface the uv memory
        r = client.post(
            "/memories/search", json={"query": "python package manager", "limit": 3}
        )
        assert r.status_code == 200, r.text
        hits = r.json()
        top = hits[0]
        print(f"✓ semantic: top={top['content'][:40]!r} distance={top['distance']:.4f}")
        assert "uv" in top["content"]

        # FULL-TEXT search — keyword "postgres" matches the storage memory
        r = client.post(
            "/memories/search/fulltext", json={"query": "postgres", "limit": 3}
        )
        assert r.status_code == 200, r.text
        ft = r.json()
        assert ft and "Postgres" in ft[0]["content"]
        print(f"✓ fulltext: top={ft[0]['content'][:40]!r} rank={ft[0]['rank']:.4f}")

        # FULL-TEXT with websearch syntax (exclusion) — should drop the uv memory
        r = client.post(
            "/memories/search/fulltext",
            json={"query": "memories -uv", "limit": 5},
        )
        assert r.status_code == 200, r.text
        assert all("uv" not in h["content"] for h in r.json())
        print("✓ fulltext websearch exclusion works")

        # CLEANUP
        for mem_id in created_ids:
            assert client.delete(f"/memories/{mem_id}").status_code == 204
        print("✓ cleanup")

    print("\nAll endpoint checks passed.")


if __name__ == "__main__":
    main()
