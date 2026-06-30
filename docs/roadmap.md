# wise-mem roadmap — typed knowledge graph + unified search

> **Purpose.** This is the high-level plan for evolving wise-mem from a memory store
> into a typed knowledge graph with unified retrieval and (later) graph algorithms.
> It exists so any agent or human can **resume the work mid-stream**. Detailed,
> per-slice design lives in `docs/superpowers/specs/`; the storage architecture
> rationale lives in [ADR 0001](./adr/0001-postgres-source-of-truth-memgraph-derived-graph.md).
>
> **Working style:** thin vertical slices, each end-to-end (model → migration →
> crud → service → API + CLI parity → tests), Conventional Commits, small
> changesets. Each slice gets its own spec + plan before implementation.

## Vision / end state

wise-mem stores and retrieves **typed content** — memories, projects, entities,
files, lexicon entries — that are **related** to each other, and exposes:

- **Unified, type-filtered search** (vector + full-text + RRF hybrid) across all
  content types from one endpoint.
- A **relationship graph** (hierarchies + typed/classified edges) over that content.
- **First-class graph traversal, algorithms, and GraphRAG retrieval** via a derived
  Memgraph projection.

## Architecture (see ADR 0001)

- **Postgres + pgvector is the durable system-of-record.** All content, embeddings,
  full-text, search, and the relational edge model live here. Alembic owns the schema.
- **Memgraph is a derived, rebuildable graph projection** (Phase 2). One-directional,
  idempotent (Postgres → rebuild → Memgraph). Not a second source of truth; no
  back-sync, no CDC. If lost, re-derive from Postgres.

## Locked design decisions

These are settled (2026-06-29) and should not be re-litigated without cause:

1. **Search spine = typed tables + app-side RRF fusion.** Each content type is its
   own table with its **own** `embedding vector(768)` + generated `content_tsv`
   (copying the existing `Memory` pattern). Unified search runs each selected type's
   vector + full-text query and fuses all ranked lists by **RRF in `service.py`**
   (generalizing the existing 2-list hybrid to N lists). Type filter = query fewer
   tables. *Rejected:* a single shared `searchable` god-table (forces a disruptive
   Memory migration; lexicon multi-sense doesn't fit) and a synced search-index
   (premature sync path).
2. **Relationships stay relational in Postgres.** **Per-pair link tables** (FK-safe,
   `ON DELETE CASCADE`, reusing the `memory_project` pattern and the `IN`-subquery
   filter rule) for cross-type edges; **adjacency-list `parent_id`** + recursive CTEs
   for hierarchy (siblings *derived* from shared parent, not stored). Classification
   carried as a `relation`/`role` column on the link table. *Rejected:* a generic
   polymorphic edge table (loses FKs; `int`/`uuid` PK mismatch). The link tables are
   the **projection source** for Phase 2 graph edges.
3. **Embeddings:** keep local Ollama `nomic-embed-text` (768-dim) for every type, via
   the existing `embed_document` / `embed_query` task-prefix seam in `embeddings.py`.
   All routed through `service.py` (the parity seam) so API and CLI never drift.
4. **Parity rule holds:** all new orchestration goes through `service.py`; `crud.py`
   stays framework-free and owns SQL; read models hide raw embeddings.
5. **Phase 2 store = Memgraph as derived projection** (not AGE, not all-in Memgraph,
   not CDC). See ADR 0001.

## Open decisions (resolve per-slice, not now)

- **PK strategy for new node types** — *proposed:* `uuid` for entity / file /
  lexicon_entry / lexicon_sense (clean external identity, matches `Project`);
  `Memory` stays `int` (legacy). Mixed PKs are fine — the Phase 2 projection
  namespaces ids (`memory:123`, `project:<uuid>`).
- **Unified-search result shape** — how to represent heterogeneous (mixed-type) hits
  in one response (discriminated union vs. common envelope + `type` + payload).
- **Which search modes each type exposes** — all of vector / full-text / hybrid, or
  hybrid-only for some types.
- **Entity subtype storage** — single-table-inheritance (`kind` + typed columns +
  JSONB tail) vs. promoting a subtype to its own table; default to STI + JSONB,
  promote only when a subtype earns it.
- **pgvector server version** — confirm **≥ 0.8** (iterative scan) so a `type`/
  project filter on HNSW does not under-return; otherwise plan an upgrade.
- **Phase 2 refresh strategy** — batch schedule vs. after-write rebuild vs. on-demand.

---

## Phase 1 — Postgres: types, relations, unified search

All in Postgres on the existing stack. No new infrastructure. Built as thin slices:

- [ ] **Slice 0 — Unified search contract + dispatcher.**
  Generalize the existing memory search into a **type-aware unified search** in
  `service.py`: a `types` filter, per-type vector + full-text candidate queries, and
  N-list RRF fusion. Define the per-type "searchable" contract (what each type must
  provide: `content`, `embedding`, `content_tsv`). Initially wired for `memory` only,
  designed to accept the new types. Establishes the heterogeneous result shape and
  the API/CLI surface for unified search. *This is the connective tissue — design it
  holistically even though only Memory is wired at first.*

- [ ] **Slice 1 — Entity (reference implementation).** ⭐ first thin slice
  The richest type, proving every hard pattern at once:
  - `entity` table — STI (`kind ∈ {person, organization, tool, website, property}`)
    + shared `name` / `content` / `embedding` / `content_tsv` + `attributes JSONB` +
    adjacency-list `parent_id` (org/department trees).
  - `external_registry` (`key`, `name`, `formatter_url`) + `entity_external_ref`
    (`entity_id`, `registry_id`, `value`, `url`) — Wikidata-style external IDs
    (github / pypi / dockerhub / CVE), `UNIQUE(entity_id, registry_id, value)`.
  - Edge tables: `entity_relation` (`src`, `dst`, `relation` — employee_of / member_of
    / owns / associated_with), `entity_link` to websites with a `path` attribute.
  - crud + `service.py` orchestration + FastAPI routes + Typer CLI at parity + tests
    + Alembic migration.
  - Plug `entity` into the Slice-0 unified search.

- [ ] **Slice 2 — File.**
  `file` table — `original_filename`, `storage_backend ∈ {local, s3, url}`, canonical
  `uri`, optional `bucket`/`storage_key`, `content_type`, `size_bytes`, `sha256`
  (dedup + integrity, partial unique index), provenance (`source`, `owner`,
  `provenance JSONB` borrowing Dublin Core vocabulary), optional extracted `content`
  (OCR/transcription) + `embedding` + `content_tsv`, `ocr_status`. Link tables
  `file_project` / `file_memory` / `file_entity`. Plug into unified search (text only
  when `content` present). Bytes live in object store / fs, not Postgres.

- [ ] **Slice 3 — Lexicon.**
  `lexicon_entry` (`term`, `normalized`, `entry_kind ∈ {acronym, word, phrase}`,
  `alt_spellings text[]` with pg_trgm GIN for fuzzy/misspelling match, `content` +
  `embedding` + `content_tsv`) + `lexicon_sense` (one row **per meaning**:
  `definition`, `context_cue`, `context_tags text[]`, per-sense `embedding`) +
  `sense_relation` (`synonym` / `antonym`, sense↔sense) + `sense_entity_link`
  (sense → entity). Senses are rows (not JSONB) — they are the join target for
  relations, entity links, and per-sense disambiguation embeddings. Plug into unified
  search (the searchable unit for a sense is the sense; the entry's `content` is a
  separate contribution).

- [ ] **Slice 4 — Project relations.**
  Make `Project` relatable: adjacency-list `parent_id` (hierarchy; siblings derived)
  + `project_entity` link (owner / associated, with `role`). Reuse the existing
  `memory_project` link. Recursive-CTE descendant/ancestor queries. Optionally extend
  project-scoped search to include a project subtree.

## Phase 2 — Memgraph: derived graph projection

Built only after Phase 1 is solid. Memgraph is a rebuildable view of Postgres.

- [ ] **Slice 5 — Graph model + projection schema.**
  Define the labeled-property-graph: multi-labels for entity subtypes
  (`:Entity:Person`, …), typed edges (`:PARENT_OF`, `:EMPLOYEE_OF {role}`, `:OWNS`,
  `:MEMBER_OF`, `:RELATES_TO`, `:LINKED_TO {path}`, `:HAS_SENSE`, `:REFERS_TO`,
  `:SYNONYM_OF`/`:ANTONYM_OF`), vector indexes on `:Memory(embedding)` /
  `:Entity(embedding)` (dim 768, cosine). Id namespacing (`memory:123`,
  `project:<uuid>`). Idempotent Cypher DDL (no Alembic equivalent — versioned scripts).

- [ ] **Slice 6 — Rebuild job (Postgres → Memgraph).**
  One-directional, idempotent build: read node tables + link tables, emit
  vertices/edges. Full rebuild first; incremental later if needed. Refresh strategy
  TBD (batch / scheduled / after-write).

- [ ] **Slice 7 — GraphRAG retrieval.**
  `vector_search.search(...)` to seed nodes, then `MATCH (seed)-[*1..2]-(ctx)` to
  expand a connected, explainable subgraph for agent retrieval. New endpoint in
  `service.py` / API / CLI.

- [ ] **Slice 8 — Graph algorithms (short-list).**
  Via MAGE, only what earns its keep on a personal graph: **pathfinding /
  shortest-path** ("how are X and Y connected?") + **BFS neighborhood expansion**
  (core); **node similarity / link prediction** ("related notes you didn't link")
  (enrichment); **PageRank** ("hub entities") (optional). **Defer** community
  detection / node2vec until the graph has scale.

## Status

| Phase | Slice | Status | Spec |
|------|-------|--------|------|
| 1 | 0 — Unified search contract | not started | — |
| 1 | 1 — Entity (reference) | **next** | — |
| 1 | 2 — File | not started | — |
| 1 | 3 — Lexicon | not started | — |
| 1 | 4 — Project relations | not started | — |
| 2 | 5 — Graph model/projection schema | not started | — |
| 2 | 6 — Rebuild job | not started | — |
| 2 | 7 — GraphRAG retrieval | not started | — |
| 2 | 8 — Graph algorithms | not started | — |

> Update this table (and link the spec) as each slice is specced / built. Slices 0
> and 1 may be specced together (the search contract is designed against Entity as the
> first real type).

## References

- [ADR 0001 — Postgres source-of-truth, Memgraph derived graph](./adr/0001-postgres-source-of-truth-memgraph-derived-graph.md)
- Research synthesis (2026-06-29): hierarchy/graph modeling, polymorphic unified
  search, entity/knowledge-graph modeling, file/asset metadata, lexicon/termbase
  modeling, Apache AGE, and the five-stream Memgraph evaluation. Key external sources
  are cited in ADR 0001.
- Contributor invariants: [`CLAUDE.md`](../CLAUDE.md). Test setup:
  [`tests/README.md`](../tests/README.md).
