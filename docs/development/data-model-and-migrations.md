# Xdocs — Data Model & Migrations

**Status:** Draft for implementation · **Date:** 2026-06-25
**Companion docs:** [Design](../design/documentation-control-design.md) · [Development Plan](./development-plan.md) · [API Spec](./api-specification.md)

PostgreSQL 16 with the `pgvector` and `pg_trgm` extensions. SQLAlchemy 2.0 (async) models; Alembic migrations. This document specifies tables, columns, indexes, and the migration/seed plan. DDL is illustrative (final column types/constraints live in migrations).

---

## 1. Extensions & Conventions

```sql
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- trigram for suggest/ILIKE
```
- PKs are `uuid` (default `gen_random_uuid()` via `pgcrypto`/`uuid-ossp`).
- All tables carry `created_at timestamptz NOT NULL DEFAULT now()` and `updated_at timestamptz NOT NULL DEFAULT now()` (trigger-updated).
- Soft-delete via `deleted_at timestamptz NULL` on content tables; queries filter it out.
- **Multi-tenant seam (design §16.6):** v1 is single-tenant, but a nullable `tenant_id uuid` column is reserved on top-level tables (`space`, `media_asset`, `analytics_event`) and all scoped queries go through a central repository layer, so a future tenant boundary needs data backfill only — no schema rewrite.

---

## 2. Entity Overview

```
space ──< product_version
  │  └──< acl
  └──< book ──< page ──< page (self, tree)
                 │  ├──< page_translation ──< page_revision
                 │  │                      └──< doc_chunk
                 │  └──< page_media (m:n) >── media_asset
analytics_event (page_view | llm_feedback | search[deferred])
llm_artifact (ephemeral)   translation_cache (ephemeral)
```

---

## 3. Tables

### 3.1 `space`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid NULL | reserved (single-tenant v1) |
| slug | citext UNIQUE | URL key |
| title | text | |
| description | text NULL | |
| default_locale | text NOT NULL | BCP-47 |
| default_version_id | uuid NULL FK→product_version | pinned default |
| landing_blocks | jsonb NULL | curated master-page blocks (§16.4) |
| meta | jsonb | |

### 3.2 `product_version`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| space_id | uuid FK→space | |
| label | text | e.g. `2019`,`2022`,`latest` |
| visibility | text NOT NULL | `internal` \| `published` (§16.5) |
| is_default | bool DEFAULT false | mirrors `space.default_version_id` |
| sort_order | int | |
| UNIQUE | (space_id, label) | |

### 3.3 `book`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| space_id | uuid FK→space | |
| version_id | uuid FK→product_version | book belongs to a version |
| slug | citext | |
| title | text | |
| sort_order | int | |
| UNIQUE | (version_id, slug) | |

### 3.4 `page` (tree node)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| book_id | uuid FK→book | |
| parent_page_id | uuid NULL FK→page | self-referential tree |
| slug | citext | |
| sort_order | int | |
| status | text NOT NULL | `draft` \| `published` |
| UNIQUE | (book_id, parent_page_id, slug) | |
| INDEX | (book_id, parent_page_id, sort_order) | tree fetch |

> Tree strategy: adjacency list (`parent_page_id`) for v1; if deep-tree queries become hot, add a materialized path (`ltree`) — noted as a future optimization, not v1.

### 3.5 `page_translation` (content lives here)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| page_id | uuid FK→page | |
| locale | text NOT NULL | BCP-47 |
| title | text | |
| markdown | text | source of truth |
| html_cached | text NULL | rendered+sanitized on publish |
| headings | jsonb NULL | extracted TOC `[{level,id,text}]` |
| translation_status | text | `human` \| `llm_draft` \| `approved` |
| revision | int NOT NULL | current revision (optimistic lock) |
| published_at | timestamptz NULL | |
| UNIQUE | (page_id, locale) | |

### 3.6 `page_revision` (history)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| page_translation_id | uuid FK | |
| revision | int | |
| markdown | text | snapshot |
| author_id | uuid | from JWT `sub` |
| created_at | timestamptz | |
| UNIQUE | (page_translation_id, revision) | |

### 3.7 `doc_chunk` (search/RAG unit)
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| page_translation_id | uuid FK | |
| ordinal | int | section order |
| content | text | chunk text |
| ts | tsvector | generated/maintained for FTS |
| embedding | vector(1536) | `text-embedding-3-small` dim |
| anchor | jsonb | `{heading_id, text}` for citations |
| INDEX | GIN on `ts` | keyword |
| INDEX | HNSW on `embedding` (`vector_cosine_ops`) | semantic |

`ts` populated as `to_tsvector(coalesce(locale-config,'simple'), content)` (locale-aware where supported; `simple` fallback).

### 3.8 `media_asset`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid NULL | reserved |
| space_id | uuid FK→space | |
| storage_key | text | object-storage key |
| content_type | text | |
| size | int | bytes |
| width/height | int NULL | for images |
| uploaded_by | uuid | |

`page_media` (m:n): `(page_id, media_asset_id)` for usage tracking / orphan cleanup.

### 3.9 `acl`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| space_id | uuid FK→space | |
| principal | text | role name or `user:<sub>` |
| permission | text | `read` \| `write` \| `admin` |
| UNIQUE | (space_id, principal, permission) | |

### 3.10 `analytics_event`
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid NULL | reserved |
| type | text | `page_view` \| `llm_feedback` \| `search`(deferred §16.7) |
| subject_id | uuid NULL | page/answer id |
| data | jsonb | `{scope, rating, comment, …}` |
| at | timestamptz | |
| INDEX | (type, at) | rollups |

### 3.11 Ephemeral tables
- `llm_artifact` — `{id, kind(summary|extract), markdown, created_by, expires_at}`. Pruned by a periodic worker. (Design §6.3: LLM outputs are download-only, not managed docs.)
- `translation_cache` — `{page_id, page_revision, locale, html, expires_at}` for on-the-fly translation fallback (§16.3). Keyed to page revision so edits invalidate it.

---

## 4. Indexing Summary

| Purpose | Index |
|---|---|
| Tree fetch | `page(book_id, parent_page_id, sort_order)` |
| Page lookup | `page_translation(page_id, locale)` unique |
| Keyword search | GIN on `doc_chunk.ts` |
| Semantic search | HNSW on `doc_chunk.embedding` (cosine) |
| Type-ahead | `pg_trgm` GIN on `page_translation.title` |
| Slugs | unique citext indexes per parent scope |
| Analytics rollups | `analytics_event(type, at)` |

HNSW build params (`m`, `ef_construction`) and query `ef_search` are tuned in a perf story (Dev Plan H3); IVFFlat is the fallback if memory-constrained.

---

## 5. Referential Integrity & Cascades

- Deleting a `space` cascades to versions/books/pages/translations/chunks (soft-delete first; hard-delete via admin maintenance job).
- `doc_chunk` rows are fully owned by their `page_translation` and regenerated on publish (delete-then-insert), keeping the index consistent.
- `media_asset` deletion blocked while referenced (`page_media`); orphans cleaned by a worker.

---

## 6. Migration Plan (Alembic)

Migrations are additive and ordered to match the [phased plan](./development-plan.md#7-work-breakdown-structure-epics--stories):

| Migration | Phase/Epic | Contents |
|---|---|---|
| `0001_baseline` | A3 | extensions; `space`, `product_version`, `book`, `page`, `page_translation`, `acl` |
| `0002_revisions` | B1/F4 | `page_revision` |
| `0003_search` | C1 | `doc_chunk` (+ ts, embedding, indexes) |
| `0004_media` | F5 | `media_asset`, `page_media` |
| `0005_analytics` | H1 | `analytics_event` |
| `0006_ephemeral` | D4/D6 | `llm_artifact`, `translation_cache` |

Rules: every migration has a reversible `downgrade`; data migrations separated from schema migrations; CI runs `upgrade head` then `downgrade base` on an ephemeral DB to verify reversibility.

---

## 7. Seed Data (dev/demo)

`app.scripts.seed` creates a self-contained demo used by the test host and E2E:
- 2 spaces (`sql-server`, `platform`), each with 2 product versions (one `published`, one `internal`).
- 1–2 books per version; a nested page tree (≥3 levels) with rich markdown (code, Mermaid, KaTeX, admonitions, tables, an image).
- Translations: full `en`, partial `fr` (to exercise fallback + on-the-fly translation), `de` missing (pure fallback).
- ACLs for `reader`/`editor`/`admin` roles matching the mock-IdP role switcher.
- Pre-generated chunks + embeddings (or generated on first publish) so search/RAG work immediately.

Seed is idempotent (safe to re-run) and used as the fixture baseline for integration/E2E tests.

---

## 8. Data Retention & Privacy

- Ephemeral `llm_artifact` / `translation_cache` expire (default 24h) and are pruned.
- Analytics store minimal data; LLM feedback comments are user-provided text (treated as content). No third-party trackers.
- LLM calls send only in-scope chunk text to the provider; Azure OpenAI option supports data-residency (design §12).

---

*End of data model & migrations spec.*
