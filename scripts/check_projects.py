"""End-to-end exercise of the projects feature against the real database.

Covers: project CRUD, linking at creation and via endpoints, the ANY-of
project filter on list + semantic/fulltext/hybrid search, manual unlink (does
NOT flag) vs project deletion (sets had_deleted_project + cascades links), and
404 paths. Requires a running Ollama (auto-embedding on create).
"""

import uuid

from fastapi.testclient import TestClient

from wise_mem.api import app


def main() -> None:
    created_memories: list[int] = []
    created_projects: list[str] = []

    with TestClient(app) as client:
        # --- project CRUD ---
        pa = client.post("/projects", json={"name": "Alpha"})
        pb = client.post("/projects", json={"name": "Beta", "description": "second"})
        assert pa.status_code == 201 and pb.status_code == 201, (pa.text, pb.text)
        a_id, b_id = pa.json()["id"], pb.json()["id"]
        created_projects += [a_id, b_id]
        uuid.UUID(a_id)  # confirm it's a real UUID
        assert client.get(f"/projects/{a_id}").json()["name"] == "Alpha"
        assert {p["id"] for p in client.get("/projects").json()} >= {a_id, b_id}
        print(f"✓ project CRUD: A={a_id[:8]} B={b_id[:8]}")

        # --- linking: at creation, via endpoint, and to both ---
        m1 = client.post(
            "/memories", json={"content": "alpha apple banana", "project_ids": [a_id]}
        ).json()
        assert m1["had_deleted_project"] is False
        m2 = client.post("/memories", json={"content": "beta cherry date"}).json()
        assert client.post(f"/memories/{m2['id']}/projects/{b_id}").status_code == 204
        m3 = client.post(
            "/memories",
            json={"content": "shared elderberry fig", "project_ids": [a_id, b_id]},
        ).json()
        created_memories += [m1["id"], m2["id"], m3["id"]]
        proj_ids = {p["id"] for p in client.get(f"/memories/{m3['id']}/projects").json()}
        assert proj_ids == {a_id, b_id}
        print("✓ linking: at-create, via-endpoint, and dual-link all work")

        # --- list filter (ANY) ---
        ids_a = {m["id"] for m in client.get(f"/memories?project_ids={a_id}").json()}
        assert m1["id"] in ids_a and m3["id"] in ids_a and m2["id"] not in ids_a
        ids_ab = {
            m["id"]
            for m in client.get(
                f"/memories?project_ids={a_id}&project_ids={b_id}"
            ).json()
        }
        assert {m1["id"], m2["id"], m3["id"]} <= ids_ab
        print("✓ list filter: A -> {m1,m3}; A|B -> all three")

        # --- search filters (semantic / fulltext / hybrid) ---
        sem_b = client.post(
            "/memories/search", json={"query": "fruit", "project_ids": [b_id]}
        ).json()
        assert m1["id"] not in {h["id"] for h in sem_b}  # m1 only in A -> excluded
        ft_a = client.post(
            "/memories/search/fulltext", json={"query": "apple", "project_ids": [a_id]}
        ).json()
        assert m1["id"] in {h["id"] for h in ft_a}
        hyb_a = client.post(
            "/memories/search/hybrid", json={"query": "shared", "project_ids": [a_id]}
        ).json()
        assert m2["id"] not in {h["id"] for h in hyb_a}  # m2 not in A
        print("✓ search filters: semantic/fulltext/hybrid all honour project_ids")

        # --- 404 paths ---
        bogus = str(uuid.uuid4())
        assert (
            client.post(
                "/memories", json={"content": "x", "project_ids": [bogus]}
            ).status_code
            == 404
        )
        assert client.post(f"/memories/{m2['id']}/projects/{bogus}").status_code == 404
        print("✓ 404s: unknown project on create and on link")

        # --- manual unlink does NOT set the flag ---
        assert client.delete(f"/memories/{m2['id']}/projects/{b_id}").status_code == 204
        assert client.get(f"/memories/{m2['id']}").json()["had_deleted_project"] is False
        print("✓ manual unlink leaves had_deleted_project False")

        # --- project deletion: flag linked memories, cascade links, keep memories ---
        assert client.delete(f"/projects/{a_id}").status_code == 204
        assert client.get(f"/projects/{a_id}").status_code == 404
        assert client.get(f"/memories/{m1['id']}").json()["had_deleted_project"] is True
        assert client.get(f"/memories/{m3['id']}").json()["had_deleted_project"] is True
        # m3 kept its B link (only A was deleted)
        assert {p["id"] for p in client.get(f"/memories/{m3['id']}/projects").json()} == {
            b_id
        }
        print("✓ project delete: sets flag, cascades A-links, memories survive")

        # --- cleanup ---
        for mid in created_memories:
            client.delete(f"/memories/{mid}")
        for pid in created_projects:
            client.delete(f"/projects/{pid}")
        print("✓ cleanup")

    print("\nAll project checks passed.")


if __name__ == "__main__":
    main()
