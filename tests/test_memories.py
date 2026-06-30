"""API tests for memory CRUD, auto-embedding, and re-embedding."""

import math

from wise_mem.db import async_session_factory
from wise_mem.embeddings import embed_query
from wise_mem.models import Memory


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / (na * nb)


def test_create_autoembeds_and_hides_vector(client):
    r = client.post("/memories", json={"content": "the sky is blue", "source": "t"})
    assert r.status_code == 201
    body = r.json()
    assert body["id"] and body["had_deleted_project"] is False
    assert "embedding" not in body  # write/search-only


def test_get_roundtrip_and_404(client):
    mid = client.post("/memories", json={"content": "hello"}).json()["id"]
    assert client.get(f"/memories/{mid}").json()["content"] == "hello"
    assert client.get("/memories/999999").status_code == 404


def test_list_newest_first(client):
    a = client.post("/memories", json={"content": "first"}).json()
    b = client.post("/memories", json={"content": "second"}).json()
    ids = [m["id"] for m in client.get("/memories").json()]
    assert ids[:2] == [b["id"], a["id"]]


def test_patch_meta_replaces_wholesale(client):
    m = client.post("/memories", json={"content": "x", "meta": {"a": 1, "b": 2}}).json()
    r = client.patch(f"/memories/{m['id']}", json={"meta": {"a": 9}})
    assert r.json()["meta"] == {"a": 9}


def test_patch_content_reembeds(client, run):
    m = client.post("/memories", json={"content": "the cat sat on the mat"}).json()
    client.patch(
        f"/memories/{m['id']}", json={"content": "quarterly revenue projections"}
    )

    async def _stored() -> list[float]:
        async with async_session_factory() as session:
            row = await session.get(Memory, m["id"])
            return [float(x) for x in row.embedding]

    stored = run(_stored())
    new_vec = run(embed_query("quarterly revenue projections"))
    old_vec = run(embed_query("the cat sat on the mat"))
    assert _cosine(stored, new_vec) < _cosine(stored, old_vec)


def test_patch_explicit_embedding_not_overwritten(client, run):
    m = client.post("/memories", json={"content": "alpha"}).json()
    vec = [0.01 * ((i % 5) + 1) for i in range(768)]
    client.patch(f"/memories/{m['id']}", json={"content": "beta", "embedding": vec})

    async def _stored() -> list[float]:
        async with async_session_factory() as session:
            row = await session.get(Memory, m["id"])
            return [float(x) for x in row.embedding]

    stored = run(_stored())
    assert max(abs(s - v) for s, v in zip(stored, vec, strict=True)) < 1e-6


def test_delete(client):
    mid = client.post("/memories", json={"content": "bye"}).json()["id"]
    assert client.delete(f"/memories/{mid}").status_code == 204
    assert client.get(f"/memories/{mid}").status_code == 404
    assert client.delete(f"/memories/{mid}").status_code == 404
