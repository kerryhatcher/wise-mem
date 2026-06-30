"""API tests for the four search modes."""

import asyncio

import pytest

from wise_mem.embeddings import embed_query

SEED = [
    "Kerry prefers uv over pip for Python projects",
    "wise-mem stores agent memories in Postgres",
    "Tailscale connects the thor server privately",
]


@pytest.fixture
def seeded(client):
    return [client.post("/memories", json={"content": t}).json()["id"] for t in SEED]


def test_semantic_finds_conceptual_match(client, seeded):
    hits = client.post(
        "/memories/search", json={"query": "python package manager", "limit": 3}
    ).json()
    assert hits and "uv" in hits[0]["content"]
    assert all("distance" in h for h in hits)


def test_fulltext_keyword(client, seeded):
    hits = client.post("/memories/search/fulltext", json={"query": "postgres"}).json()
    assert hits and "Postgres" in hits[0]["content"] and "rank" in hits[0]


def test_fulltext_websearch_exclusion(client, seeded):
    hits = client.post(
        "/memories/search/fulltext", json={"query": "memories -uv"}
    ).json()
    assert all("uv" not in h["content"] for h in hits)


def test_hybrid_scores_descending(client, seeded):
    hits = client.post(
        "/memories/search/hybrid", json={"query": "postgres memories", "limit": 3}
    ).json()
    assert hits and "score" in hits[0]
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_vector_search(client, seeded):
    vec = asyncio.run(embed_query("python"))
    hits = client.post(
        "/memories/search/vector", json={"embedding": vec, "limit": 3}
    ).json()
    assert hits and "distance" in hits[0]
