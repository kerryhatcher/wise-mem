"""End-to-end exercise of the FastAPI endpoints against the real database.

Uses Starlette's TestClient, which runs the app lifespan (init_db) and drives
the async app in-process — no separate server needed.
"""

from fastapi.testclient import TestClient

from wise_mem.api import app
from wise_mem.models import EMBEDDING_DIM


def main() -> None:
    query_vec = [0.1] * EMBEDDING_DIM

    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        print("✓ health")

        # CREATE
        r = client.post(
            "/memories",
            json={
                "content": "Kerry prefers uv over pip",
                "source": "check_api",
                "meta": {"tags": ["pref", "tooling"], "confidence": 0.95},
                "embedding": query_vec,
            },
        )
        assert r.status_code == 201, r.text
        created = r.json()
        mem_id = created["id"]
        assert "embedding" not in created  # write/search-only by design
        print(f"✓ create: id={mem_id} meta={created['meta']}")

        # READ one
        r = client.get(f"/memories/{mem_id}")
        assert r.status_code == 200 and r.json()["content"].startswith("Kerry")
        print("✓ get")

        # LIST
        r = client.get("/memories?limit=10")
        assert r.status_code == 200 and any(m["id"] == mem_id for m in r.json())
        print(f"✓ list: {len(r.json())} row(s)")

        # SEARCH
        r = client.post("/memories/search", json={"embedding": query_vec, "limit": 5})
        assert r.status_code == 200, r.text
        hits = r.json()
        assert hits and hits[0]["id"] == mem_id
        print(f"✓ search: top hit id={hits[0]['id']} distance={hits[0]['distance']:.4f}")

        # UPDATE (partial: replace meta, change content)
        r = client.patch(
            f"/memories/{mem_id}",
            json={"content": "Kerry strongly prefers uv", "meta": {"tags": ["pref"]}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["meta"] == {"tags": ["pref"]}  # replaced, not merged
        print(f"✓ patch: content={r.json()['content']!r} meta={r.json()['meta']}")

        # DELETE
        assert client.delete(f"/memories/{mem_id}").status_code == 204
        assert client.get(f"/memories/{mem_id}").status_code == 404
        print("✓ delete + 404 confirmed")

    print("\nAll endpoint checks passed.")


if __name__ == "__main__":
    main()
