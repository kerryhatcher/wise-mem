"""Text embedding via a local Ollama server (nomic-embed-text).

nomic-embed-text expects task-instruction prefixes: `search_document:` for text
being stored, `search_query:` for a search query. We add the right prefix for
the caller so query/document embeddings stay aligned.
"""

import httpx

from wise_mem.config import settings

_DOCUMENT_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "


class EmbeddingError(RuntimeError):
    """Raised when the embedding backend is unreachable or returns an error."""


async def _embed(text: str) -> list[float]:
    url = f"{settings.ollama_host.rstrip('/')}/api/embed"
    payload = {"model": settings.embedding_model, "input": text}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:  # network error, timeout, non-2xx
        raise EmbeddingError(f"Ollama embedding request failed: {exc}") from exc

    embeddings = data.get("embeddings")
    if not embeddings:
        raise EmbeddingError(f"Ollama returned no embeddings: {data}")
    return embeddings[0]


async def embed_document(text: str) -> list[float]:
    """Embed text that will be stored as a memory."""
    return await _embed(_DOCUMENT_PREFIX + text)


async def embed_query(text: str) -> list[float]:
    """Embed a search query."""
    return await _embed(_QUERY_PREFIX + text)
