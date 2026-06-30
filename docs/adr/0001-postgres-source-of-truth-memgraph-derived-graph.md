# ADR 0001 — Postgres is the system-of-record; Memgraph is a derived graph projection

- **Status:** Accepted
- **Date:** 2026-06-29
- **Deciders:** Kerry Hatcher
- **Tags:** storage, architecture, search, graph, memgraph, postgres, pgvector

## Context

wise-mem is expanding from a memory store into a small **typed knowledge graph**. The
next major version adds three new content datatypes (**entity**, **file**, **lexicon**),
makes **projects relatable** (hierarchy + associations), and refactors search into a
**unified, type-filtered** endpoint. Three capabilities must coexist:

1. **Content + retrieval** — document-like text with vector search (pgvector,
   `nomic-embed-text`, 768-dim), full-text search (`tsvector`), and hybrid
   Reciprocal Rank Fusion (RRF). This is wise-mem's core and already works.
2. **A typed knowledge graph** — people, orgs, tools, websites, property, projects,
   files, lexicon entries/senses; hierarchies and typed/classified edges
   (employee_of, owns, parent_of, …).
3. **First-class graph traversal and algorithms** — pathfinding, neighborhood
   expansion, node similarity / link prediction, centrality, and GraphRAG-style
   retrieval (vector-seed → traverse) over that graph.

The current stack is **Postgres + pgvector + async SQLAlchemy/SQLModel + FastAPI +
Typer**, with **Alembic** as the single source of schema truth. The project is early
and willing to change stores. A **Memgraph** server is already available. We
evaluated Apache AGE earlier and rejected it (see "Alternatives").

The question: where should each capability live? Candidate architectures were
**(1) all-in Memgraph**, **(2) Postgres + Memgraph as two synced sources of truth**,
and **(3) Postgres only**.

## Decision

**Postgres + pgvector remains the durable system-of-record** for all content,
embeddings, full-text, type-filtered hybrid search, and the relational edge model
(per-pair link tables + adjacency-list hierarchy).

**Memgraph becomes a derived, rebuildable graph *projection*** — not a second source
of truth. It is built **one-directionally and idempotently** from Postgres
(Postgres → rebuild → Memgraph) and provides graph traversal, MAGE algorithms, and
GraphRAG retrieval. If the Memgraph image is ever lost, it is re-derived from
Postgres; there is no back-sync and no cross-store transaction.

The work is **phased**:

- **Phase 1 (Postgres only):** the three new types + project relations + unified
  type-filtered RRF search. Ships value on the existing, well-tooled stack with no
  new infrastructure.
- **Phase 2 (Memgraph projection):** a rebuild job (Postgres → graph), a GraphRAG
  retrieval path, and a short-list of graph algorithms.

To keep Phase 2 cheap, Phase 1 edges are modeled as **typed, directional link
tables** that project cleanly into graph edges; mixed `int`/`uuid` primary keys are
**namespaced** at projection time (e.g. `memory:123`, `project:<uuid>`).

## Rationale

A five-stream research review (2026-06-29) converged, from independent angles, on the
same conclusion.

**Why not all-in Memgraph (Architecture 1):**

- **Durability lives in RAM.** Memgraph's only production-grade mode is
  `IN_MEMORY_TRANSACTIONAL`; `ON_DISK_TRANSACTIONAL` is explicitly *not*
  production-ready. Durable truth would sit in volatile RAM behind periodic
  snapshots + a buffered (not per-commit-fsync'd) WAL — a small but real data-loss
  window. For a *memory* store, "truth in RAM" is the wrong default. (RAM *size* is
  not the issue — 50k 768-dim vectors ≈ ~150 MB.)
- **Weakest exactly where our core feature is strongest.** Memgraph's query planner
  does **not** use the vector index for filtering, so a `type` predicate is a
  *post*-filter that under-fills sparse types; there is **no native hybrid/RRF**.
  Our unified, type-filtered hybrid search is better served by pgvector's filtered
  ANN (with iterative scan) + app-side RRF.
- **Developer-experience regression.** Async requires the `neo4j` driver + hand-written
  Cypher (no async OGM — we lose SQLModel's typed models), and there is **no Alembic
  equivalent** (DIY idempotent Cypher migrations, no history/downgrade).
- **Ops/licensing.** Manual lock/copy/recover backups; automatic-failover HA is
  Enterprise.

**Why not two synced sources of truth (Architecture 2 with CDC):** a bidirectional /
CDC-synced design (Debezium, outbox) inherits the **dual-write problem** — drift,
orphans, partial writes, replication-slot WAL growth, and "which store is right?"
debugging. That machinery is **disproportionate** for a single-user, self-hosted app.

**Why the derived-projection middle path wins:** it is **one-directional and
idempotent**, so there is no dual-write tax and no consistency ambiguity — Postgres is
always authoritative. A stale-then-refreshed graph is perfectly adequate for the
algorithms that matter (centrality, communities, similarity) and for batch GraphRAG
index builds. We keep durable disk-first storage, Alembic, and typed async models,
**and** gain Memgraph's genuine strengths (one-query vector-seed-then-traverse;
MAGE pathfinding / BFS expansion / node similarity).

## Consequences

**Positive**

- Core search, durability, and tooling (pgvector, RRF, Alembic, SQLModel) are
  preserved and extended, not rewritten.
- Graph traversal, GraphRAG, and graph algorithms become available without a second
  source of truth or CDC infrastructure.
- Clean decomposition into two independently shippable phases; Phase 1 needs no new
  infrastructure.
- Losing the Memgraph image is a non-event — rebuild from Postgres.

**Negative / costs**

- A projection/rebuild component must be built and operated (Phase 2): a
  Postgres → Memgraph mapping, a refresh trigger/schedule, and a namespacing scheme
  for ids.
- The graph is **eventually consistent** with Postgres (staleness between rebuilds).
  Acceptable for analytics/GraphRAG; not suitable for read-after-write graph reads
  that must be live. If live graph state at scale is ever required, revisit toward a
  properly-done outbox/CDC design.
- Two systems to run in Phase 2 (Postgres + Memgraph), though only one holds truth.

**Neutral**

- Edge model stays relational in Postgres (per-pair link tables, adjacency-list
  hierarchy), chosen for referential integrity and to serve project-scoped search;
  the link tables are the projection source for graph edges.

## Alternatives considered

- **Apache AGE (openCypher inside Postgres).** Rejected earlier: shallow-traversal
  needs don't justify it; its strength (deep variable-length traversal) is where it
  currently underperforms (index bypass); no ORM (agtype parsing, per-connection
  `LOAD 'age'`); and it is unavailable on most managed Postgres (RDS/Supabase/Neon).
- **All-in Memgraph (Architecture 1).** Rejected — see Rationale (durability in RAM,
  type-filtered-search weakness, DX regression).
- **Postgres + Memgraph as synced sources of truth via CDC (Architecture 2).**
  Rejected as disproportionate for a single-user app (dual-write problem, CDC
  middleware tax).
- **Postgres only, forever (Architecture 3).** Rejected as the *end state* because
  recursive CTEs cannot practically deliver real graph algorithms; retained as the
  **Phase 1** substrate and the permanent system-of-record.

### Conditions that would reopen this decision

- Graph algorithms become the #1 requirement **and** durability tolerance increases
  **and** the corpus comfortably fits RAM → reconsider all-in Memgraph.
- A requirement for **live** (not batch-stale) graph state at scale → graduate the
  projection to a properly-done outbox/CDC sync.
- Corpus grows beyond comfortable RAM, or stronger durability/PITR is needed →
  Postgres-authoritative is reinforced; Memgraph stays a derived replica.

## References

Research conducted 2026-06-29 (Memgraph docs v3.x basis). Key sources:

- Memgraph vector search (USearch/HNSW; planner does not use index for filtering):
  <https://memgraph.com/docs/querying/vector-search>
- Memgraph text search (Tantivy/BM25): <https://memgraph.com/docs/querying/text-search>
- Memgraph data durability (snapshots + WAL): <https://memgraph.com/docs/fundamentals/data-durability>
- Memgraph storage modes (in-memory vs on-disk experimental): <https://memgraph.com/blog/memgraph-storage-modes-explained>
- Memgraph GraphRAG: <https://memgraph.com/docs/ai-ecosystem/graph-rag>
- MAGE algorithms: <https://memgraph.com/docs/advanced-algorithms/available-algorithms>
- neo4j Python async driver: <https://neo4j.com/docs/api/python-driver/current/async_api.html>
- gqlalchemy OGM (sync-only): <https://github.com/memgraph/gqlalchemy>
- pgvector 0.8 iterative scan (filtered ANN): <https://www.postgresql.org/about/news/pgvector-080-released-2952/>
- Reciprocal Rank Fusion (Cormack et al., 2009): <https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf>
- Dual-write problem: <https://auth0.com/blog/handling-the-dual-write-problem-in-distributed-systems/>
- Transactional outbox pattern (AWS): <https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html>
