# Handoff — design the Entity slice (Slice 0 + Slice 1)

**Audience:** a fresh AI agent (or human) starting the first thin slice of wise-mem's
knowledge-graph evolution, with no prior conversation context.
**Created:** 2026-06-29.
**You are producing a _design spec_, not code yet.** End state of this task: an
approved spec in `docs/superpowers/specs/`, then an implementation plan. Get design
approval before writing implementation code.

---

## 1. Your task

Design **Slice 0 (unified type-filtered search contract)** and **Slice 1 (Entity, the
reference content type)** together — the search contract is designed against Entity as
its first real non-memory type. Deliver one spec covering both.

- **Slice 0** generalizes wise-mem's existing memory search into a **type-aware unified
  search**: a `types` filter, per-type vector + full-text candidate queries, and N-list
  **Reciprocal Rank Fusion (RRF)** in `service.py`. Wire it for `memory` first, but
  design it to accept `entity` (and later file/lexicon).
- **Slice 1** adds the **Entity** type end-to-end: model → Alembic migration → `crud.py`
  → `service.py` → FastAPI routes → Typer CLI **at parity** → pytest tests, plus
  plugging Entity into the Slice-0 unified search.

Entity is deliberately first because it exercises every hard pattern at once
(subtypes, external references, typed edges, search integration). Once it's proven,
File and Lexicon are largely mechanical repetitions.

## 2. Read these first (in order)

1. [`docs/roadmap.md`](../roadmap.md) — the full Phase 1 + 2 plan, locked decisions,
   open decisions, and slice list. **This is your map.**
2. [`docs/adr/0001-postgres-source-of-truth-memgraph-derived-graph.md`](../adr/0001-postgres-source-of-truth-memgraph-derived-graph.md)
   — why Postgres is the system-of-record and Memgraph is a deferred derived
   projection. Don't reopen this.
3. [`CLAUDE.md`](../../CLAUDE.md) — the architecture invariants you must preserve
   (parity seam, `crud.py` framework-free, read models hide embeddings, Alembic-only
   schema, async gotchas).
4. The current code, to copy its proven patterns:
   - `wise_mem/models.py` — `Memory` (note `embedding vector(768)`, generated
     `content_tsv`, JSONB `meta`) and `Project`; the `*Create`/`*Read`/`*Query` split.
   - `wise_mem/crud.py` — SQL patterns incl. `_project_filter` (`IN`-subquery, **not**
     a JOIN), the three search functions, and `search_memories_hybrid` (the RRF you
     will generalize).
   - `wise_mem/service.py` — the parity seam both API and CLI call.
   - `wise_mem/api.py`, `wise_mem/cli.py` — the surfaces to keep at parity.
   - `wise_mem/embeddings.py` — `embed_document` / `embed_query` task-prefix seam.
   - `tests/` + [`tests/README.md`](../../tests/README.md) — integration-first setup.

## 3. Process to follow

Use the **brainstorming** skill (design before code). Work the open decisions in §5
one at a time, present the design in sections for approval, then write the spec to
`docs/superpowers/specs/YYYY-MM-DD-entity-slice-design.md`, commit it, and only then
move to the **writing-plans** skill for the implementation plan. Conventional Commits,
small changesets. After the spec lands, update the status table in `docs/roadmap.md`
(link the spec).

## 4. What is ALREADY DECIDED — do not re-litigate

(Full rationale in the roadmap §"Locked design decisions" and ADR 0001.)

1. **Search spine = typed tables + app-side RRF.** Each content type is its own table
   with its **own** `embedding vector(768)` + generated `content_tsv` (copy Memory's
   pattern). Unified search fuses per-type ranked lists by **RRF in `service.py`**.
   *Not* a shared god-table; *not* a synced search-index.
2. **Relationships stay relational:** per-pair link tables (FK + `ON DELETE CASCADE`,
   reusing the `memory_project` pattern and the `IN`-subquery filter) for edges;
   adjacency-list `parent_id` + recursive CTEs for hierarchy (siblings derived).
3. **Embeddings:** local Ollama `nomic-embed-text`, 768-dim, via the existing
   `embed_document`/`embed_query` seam, routed through `service.py`.
4. **Parity rule:** all orchestration in `service.py`; `crud.py` stays framework-free
   (owns SQL); `*Read` models hide raw embeddings.
5. **Memgraph is Phase 2** and out of scope for this slice — but model edges as typed,
   directional link tables so they project cleanly later.

## 5. Open decisions to resolve IN THIS SLICE (with recommendations)

Work these with the user; my recommendations are starting points, not mandates.

1. **PK strategy.** *Recommended:* `uuid` for `entity` (matches `Project`; clean
   external identity). `Memory` stays `int` (legacy). Mixed PKs are fine — Phase 2
   namespaces ids (`memory:123`, `entity:<uuid>`).
2. **Unified-search result shape.** How to return heterogeneous hits. *Options:* a
   discriminated union (`type` + typed payload) vs. a common envelope
   (`{type, id, score, ...summary}`). *Lean:* common envelope with `type` + the
   type's `*Read` payload + the fused `score`; easy for CLI table output and API.
3. **Search modes per type.** *Recommended:* expose vector / full-text / hybrid
   uniformly (Entity has `content`, so all three apply). Keep the existing
   memory-specific endpoints; add the unified endpoint alongside.
4. **Entity subtype storage.** *Recommended:* single-table inheritance — one `entity`
   table, `kind ∈ {person, organization, tool, website, property}`, shared columns +
   `attributes JSONB` for the type-specific tail. Add `CHECK`/validation for required
   per-kind fields. Promote a subtype to its own table only if it later earns it.
5. **pgvector ≥ 0.8 verification.** The unified search may filter HNSW by type/project;
   pre-0.8 HNSW under-returns under a selective filter (needs iterative scan). **The
   remote DB was unreachable during planning — verify the server extension version
   before relying on filtered ANN.** Check with:
   `SELECT extversion FROM pg_extension WHERE extname='vector';` If < 0.8, plan an
   upgrade or design around it (e.g. per-type tables already avoid a type-discriminator
   filter; a project filter is an `IN`-subquery, so confirm whether under-return bites
   in practice).

## 6. Intended Entity shape (research-backed starting sketch)

A starting point — refine in the spec. (Sources in §9.)

```
entity                                 -- single-table inheritance
  id            uuid    PK
  kind          text    not null       -- person|organization|tool|website|property
  name          text    not null
  content       text                   -- markdown; embedded + full-text searchable
  embedding     vector(768)            -- nullable until embedded (copy Memory)
  content_tsv   tsvector  GENERATED     -- to_tsvector('english', ...); GIN index
  attributes    jsonb   not null default '{}'   -- type-specific tail (role, cli_vs_saas, serial_no, ...)
  parent_id     uuid    FK->entity.id  -- org/department hierarchy; CHECK (id <> parent_id) + cycle guard
  created_at / updated_at timestamptz

external_registry                      -- Wikidata-style external IDs
  id, key UNIQUE, name, formatter_url  -- e.g. 'github' -> 'https://github.com/$1'

entity_external_ref
  id, entity_id FK, registry_id FK,
  value,            -- the path/identifier, e.g. 'org/repo' or 'CVE-2024-1234'
  url,              -- optional explicit override
  UNIQUE(entity_id, registry_id, value)

entity_relation                        -- typed entity<->entity edges
  src_entity_id FK, dst_entity_id FK,
  relation,         -- employee_of|member_of|owns|associated_with|...
  UNIQUE(src_entity_id, dst_entity_id, relation)

entity_link                            -- entity -> website with a path on the edge
  src_entity_id FK, dst_entity_id FK,  -- dst is an entity of kind 'website'
  path,             -- e.g. '/org/repo'; the path qualifies THIS edge
  anchor_text, note,
  UNIQUE(src_entity_id, dst_entity_id, path)
```

Key modeling notes: a **website is its own entity** (`kind='website'`) so it isn't
duplicated; the **path lives on the edge**, not the website. External registries with
formatter URLs cover github/pypi/dockerhub/CVE.

Pydantic/SQLModel: follow Memory's `EntityBase` / `Entity(table=True)` /
`EntityCreate` / `EntityRead` (hides embedding) / `EntityUpdate` /
`EntitySearchHit` split. Entity↔project / entity↔memory links can reuse the link-table
pattern if in scope; otherwise defer to Slice 4.

## 7. Slice 0 — unified search contract to design

- A `service.py` entry point: `unified_search(query, *, types: list[str], mode,
  limit, project_ids=None)` where `mode ∈ {vector, fulltext, hybrid}`.
- For each selected type, run its vector and/or full-text candidate query (generous
  pool, like the existing `pool=50`), then **RRF-fuse all lists by rank** (reuse the
  `1/(k+rank)` logic from `search_memories_hybrid`, generalized to N lists).
- Return the chosen heterogeneous result shape (decision §5.2).
- Add a unified endpoint to `api.py` and a parity command to `cli.py` (human table +
  `--json`, matching the existing CLI conventions).
- Define the **per-type "searchable" contract**: each searchable type provides
  `content`, `embedding`, `content_tsv`, an id, and a `*Read` payload. Document it so
  File/Lexicon can implement it next.
- Wire `memory` (and `entity` once it exists) into the dispatcher. Keep existing
  per-type memory search endpoints working (no regressions).

## 8. Invariants to respect (from CLAUDE.md)

- **Alembic is the single schema source** — hand-write the migration; autogenerate
  can't handle `vector`, the generated `content_tsv`, or HNSW/GIN opclasses. Use
  `op.execute(...)` for those (see the existing initial migration).
- **`crud.py` imports no FastAPI/Typer.** SQL lives there; orchestration in
  `service.py`; HTTP/exit-code translation in `api.py`/`cli.py`.
- **Read models hide embeddings.** `EntityRead` omits the raw vector.
- **Async:** use SQLModel `AsyncSession` (`.exec()`), `expire_on_commit=False`; tests
  use `NullPool` (`DB_NULLPOOL=true`). The project filter is an `IN`-subquery, never a
  JOIN (a JOIN fans out duplicate rows and corrupts ranking/limit).
- **Project link `had_deleted_project`** semantics are Memory-specific; don't
  generalize them onto Entity without discussion.

## 9. Verification & environment

- `just` recipes: `just test`, `just lint`, `just fmt`, `just migrate`,
  `just revision "msg"`, `just serve`, `just cli ...`.
- Tests run against a dedicated `wisemem_test` DB (conftest rewrites the DB name);
  first-time bootstrap: `just test-db`. Requires Postgres + pgvector **and** a running
  Ollama with `nomic-embed-text`.
- Confirm the pgvector server version (§5.5) before relying on filtered ANN.
- `.env` holds `DATABASE_URL` (gitignored) — never commit credentials.

## 10. Definition of done (this slice)

- [ ] Spec approved and committed under `docs/superpowers/specs/`.
- [ ] `entity` + `external_registry` + `entity_external_ref` + `entity_relation` +
      `entity_link` tables, via a hand-written Alembic migration (up/down round-trips).
- [ ] Entity CRUD in `crud.py`; orchestration in `service.py`; FastAPI routes; Typer
      CLI at parity (human table + `--json`).
- [ ] Unified search dispatcher in `service.py` with a `types` filter + N-list RRF;
      unified endpoint + CLI command; `memory` and `entity` both searchable; no
      regression to existing memory search.
- [ ] Integration tests (real DB + real embedder) for Entity CRUD, links/relations,
      external refs, hierarchy, and unified/type-filtered search.
- [ ] `just lint` + `just test` green; `docs/roadmap.md` status table updated.

## 11. Condensed research backing (so you needn't re-research)

From the 2026-06-29 research (full sources in ADR 0001):

- **Subtypes:** single-table inheritance + JSONB tail is the pragmatic default for a
  small app (Fowler STI; schema.org/Wikidata stay generic; CMDB uses class-table
  inheritance only because enterprise governance demands it). Promote to class-table
  only when a subtype earns it. EAV is an antipattern — use real columns + JSONB, not
  a key/value table.
- **External references:** the Wikidata external-ID pattern — a `registry` with a
  `formatter_url` + a per-entity `value` (the path/id). Same app row points at
  github/pypi/dockerhub/CVE, each its own ref row.
- **Website-as-entity:** model the site as one entity; put the **path on the edge** so
  a shared site isn't duplicated and "all entities at github.com" stays queryable.
- **Unified search:** RRF is **rank-based**, so fusing per-type lists needs **no score
  normalization** — that's exactly why app-side fusion across separate tables is safe.
  Watch for per-type LIMIT truncation (fetch a generous pool before fusing) and HNSW
  under-return under selective filters (pgvector ≥ 0.8 iterative scan).
- **Antipatterns to avoid:** polymorphic-FK edge tables (no real FKs), god-tables
  (sparse nullable columns), comparing raw vector distances across types as if
  calibrated (fuse by rank instead), N+1 per-type fan-out (parallelize with
  `asyncio.gather`; fine at small N).
