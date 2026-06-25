# Xdocs — Development Plan

**Status:** Draft for execution · **Date:** 2026-06-25 · **Owner:** sgbhavsar
**Companion docs:** [Design](../design/documentation-control-design.md) · [API Spec](./api-specification.md) · [Data Model](./data-model-and-migrations.md) · [Test Plan](../testing/test-plan.md) · [Test Cases](../testing/test-cases.md)

---

## 1. Purpose & Audience

This document is the engineering plan used to build Xdocs. It translates the [design](../design/documentation-control-design.md) into a concrete, sequenced, estimable body of work, and defines how the team sets up, builds, reviews, and ships.

Audience: engineers, reviewers, and the product owner. It assumes the design decisions in Section 16 of the design doc are settled.

**Planning assumptions (adjust as needed):**
- Estimates use **story points** (Fibonacci 1/2/3/5/8/13), not calendar dates. A nominal **2-week sprint** is used for sequencing; a small team of **2–4 engineers** is assumed.
- "Done" means merged to the integration branch, behind tests + CI green, per the [Definition of Done](#10-definition-of-ready--done).
- Open source, permissive license (Apache-2.0/MIT TBD). Public-quality docs and commit hygiene apply from day one.

---

## 2. Architecture Recap (build view)

| Layer | Technology | Deliverable artifacts |
|---|---|---|
| Reader control | Web Component (`<xdocs-viewer>`, `<xdocs-master>`), vanilla JS + Tailwind (Shadow DOM) | `xdocs.js` bundle, CSS-in-shadow |
| Admin / CMS | `<xdocs-admin>` + CodeMirror 6 | `xdocs-admin.js` bundle |
| Host SDK | `xdocs-sdk.js` | tiny JS API for hosts |
| Backend | FastAPI + SQLAlchemy 2 (async) + Alembic + Pydantic v2 | `xdocs-api` image |
| Workers | arq/Celery | `xdocs-worker` image |
| PDF | Playwright/Chromium | `xdocs-pdf` image |
| Data | PostgreSQL 16 + pgvector, Redis, S3/MinIO | migrations, buckets |
| LLM | OpenAI/Azure (GPT-4o-class chat + `text-embedding-3-small`) | provider adapter |
| Test host | Static HTML + Node mock-IdP | `examples/test-host` |

See the design doc §2 for the full architecture diagram and §14 for the repository layout.

---

## 3. Repository & Module Map

```
xdocs/
  frontend/
    viewer/      # <xdocs-viewer>, <xdocs-master>
    admin/       # <xdocs-admin>
    sdk/         # host SDK
    shared/      # render enhancers, theming tokens, i18n bundles, utils
    build/       # esbuild/vite-lib config, Tailwind config
    tests/       # unit (vitest) + component tests
  backend/
    app/
      core/      # config, security, db, deps, errors, logging
      auth/      # JWT/JWKS validation, permission mapping
      content/   # spaces, books, pages, render, headings
      versions/  # product versions + draft/publish + revisions
      media/     # uploads, storage adapter
      search/    # indexing + hybrid query
      llm/       # provider abstraction, RAG, summarize, extract, translate
      export/    # PDF jobs
      i18n/      # locales, translations
      analytics/ # events, feedback
      admin/     # CMS endpoints
    workers/     # embeddings, indexing, pdf, translation
    migrations/  # alembic
    tests/       # pytest (unit + integration)
  examples/test-host/   # static page + node mock-IdP
  deploy/        # docker, compose, helm
  e2e/           # Playwright specs (web + responsive)
  docs/
```

Module ownership and boundaries follow the design doc §4.2 (modular monolith for the API + separate worker/PDF deployments).

---

## 4. Development Environment Setup

**Prerequisites**
- Docker + Docker Compose
- Python 3.12+, `uv` (or `pip`/`poetry`) for backend
- Node 20+ and `pnpm` for frontend
- Make (optional convenience targets)

**One-command bring-up (target experience)**
```bash
git clone <repo> && cd xdocs
cp .env.example .env            # set OPENAI/AZURE keys, dev signing key
docker compose up --build       # api, worker, pdf, postgres(pgvector), redis, minio, test-host
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.scripts.seed   # sample spaces/books/pages, locales, versions
# open the test host:
open http://localhost:8080      # static page embedding <xdocs-viewer>
# API docs:
open http://localhost:8000/docs # FastAPI OpenAPI UI
```

**Frontend dev loop**
```bash
cd frontend && pnpm install && pnpm dev   # watch build of xdocs.js + admin, served to test-host
```

**Key environment variables** (documented fully in `.env.example`)
- `DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`/`S3_BUCKET`/keys
- `LLM_PROVIDER` (`openai`|`azure`), `OPENAI_API_KEY` / Azure endpoint + deployment names, `LLM_CHAT_MODEL`, `LLM_EMBED_MODEL`
- `LLM_MONTHLY_BUDGET_USD`, rate-limit settings
- `JWT_ISSUER`, `JWT_AUDIENCE`, `JWKS_URL` (points at host IdP; in dev, at the mock-IdP)
- `CORS_ALLOWED_ORIGINS`

---

## 5. Coding Standards & Tooling

**Python (backend)**
- Format/lint: **ruff** (lint + format) + **mypy** (typed; `strict` on new modules).
- Async SQLAlchemy 2.0 patterns; Pydantic v2 schemas; no business logic in routers (service layer).
- Tests: **pytest** + `pytest-asyncio` + `httpx.AsyncClient`; factories via `factory_boy`/fixtures.

**JavaScript/CSS (frontend)**
- Vanilla JS modules (ES2022). No SPA framework in the reader; allowed focused libs only (design §3.6).
- Format/lint: **prettier** + **eslint**. Type-checking via **JSDoc + `tsc --checkJs`** (keeps "pure JS" while gaining types).
- Tailwind compiled into Shadow DOM stylesheet; design tokens as CSS custom properties (`--xdocs-*`).
- Tests: **vitest** + `@web/test-runner` (or jsdom) for component behavior.

**Cross-cutting**
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`…).
- Pre-commit hooks run formatters + linters on staged files.
- Every PR: green CI (lint, type, unit, integration, E2E smoke), ≥1 review, updated tests/docs.

---

## 6. Branching, Reviews & CI/CD

- **Branching:** trunk-based with short-lived feature branches off `main` (or the active integration branch). Squash-merge with a clean Conventional Commit title.
- **PR rules:** small, focused PRs; description links the epic/story; checklist (tests, docs, a11y, mobile) enforced.
- **CI pipeline (per PR):** install → lint+format check → type check → backend unit+integration (ephemeral Postgres/Redis services) → frontend unit/component → build bundles → **E2E smoke** (Playwright against compose) → security/static scans. Coverage uploaded; quality gates enforced (see Test Plan §8).
- **CD:** on merge to `main`, build & push images, run migrations on staging, deploy via Helm; promote to release tags. (See design §13.)

---

## 7. Work Breakdown Structure (Epics → Stories)

Estimates in **story points (SP)**. Stories are sized for ≤ a few days each. Acceptance criteria (AC) summarized; full test mapping in the Test Cases doc.

### EPIC A — Platform Foundations *(Phase 0)*  — ~21 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| A1 | Repo scaffold, CI pipeline skeleton, pre-commit, license | 3 | CI runs lint/type/test on empty modules; green |
| A2 | FastAPI skeleton: config, async DB session, health/readiness, error envelope, OpenAPI | 3 | `/health`,`/ready` pass; structured errors; `/docs` renders |
| A3 | Postgres+pgvector+Redis+MinIO via compose; Alembic baseline | 3 | `alembic upgrade head` works; pgvector extension enabled |
| A4 | Auth: JWT validation against JWKS, claim→permission mapping, `current_user` dep | 5 | Valid token passes; bad sig/aud/iss/exp rejected with 401/403 |
| A5 | Web Component build pipeline + Tailwind-in-shadow; empty `<xdocs-viewer>` mounts | 3 | Component renders in test host; styles isolated |
| A6 | **Test host**: static page + Node mock-IdP (`/auth/token` + JWKS) wired to API | 4 | End-to-end demo JWT validated by API; role switcher works |

### EPIC B — Content Model & Read Experience *(Phase 1, mobile-first)* — ~42 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| B1 | Schema: spaces/books/pages tree, translations, revisions, versions (default locale) | 5 | Migrations + models; tree integrity constraints |
| B2 | Content read API: space list, nav tree, page (HTML+headings+meta) | 5 | ACL-filtered; ETag caching; tree lazy-load |
| B3 | Server-side markdown render (markdown-it-py) + sanitize + heading extraction | 5 | GFM, anchors, sanitized HTML; headings JSON returned |
| B4 | `<xdocs-viewer>` three-pane layout (left nav, content, right TOC, scroll-spy) | 8 | Panes render; TOC scroll-spy; deep-link nav events |
| B5 | Client render enhancers: highlight.js, Mermaid, KaTeX, admonitions, copy-code | 5 | All render inside shadow root; XSS-safe |
| B6 | **Mobile responsiveness (§3.2.1)**: swipe drawer, bottom-sheet TOC, sticky search, container breakpoints | 8 | Works at phone/tablet/desktop; 44px targets; safe-area |
| B7 | Theming tokens (light/dark/auto), logo slot | 3 | Token overrides flow; theme switch persists |
| B8 | `<xdocs-master>` master page: data-driven cards + optional curated blocks | 3 | Spaces auto-listed; curated block slot renders |

### EPIC C — Search *(Phase 2)* — ~26 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| C1 | Chunking pipeline (section-sized) + `DOC_CHUNK` model with tsvector + vector | 5 | Chunks created on publish; anchors captured |
| C2 | Embeddings worker (text-embedding-3-small) + index maintenance (HNSW/IVFFlat, GIN) | 5 | Embeddings generated/refreshed; stale pruned |
| C3 | Hybrid search API: FTS + vector + RRF fusion + scope/ACL filters | 8 | Ranked grouped results with anchors+snippets |
| C4 | Search UI: global bar, type-ahead, grouped results, highlight | 5 | Type-ahead suggestions; result grouping; mobile sticky |
| C5 | Scope selector (page/book/space/corpus) | 3 | Scope narrows/widens results; ACL respected |

### EPIC D — LLM Features *(Phase 3)* — ~34 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| D1 | `LLMProvider` abstraction (OpenAI/Azure), config, budget guard, rate limits | 5 | Provider switchable; budget/limit enforced |
| D2 | RAG Ask: retrieve-in-scope → grounded prompt → SSE stream → citations | 8 | Streamed answer; citations link to page/anchor; "not covered" path |
| D3 | Ask panel UI (desktop + full-screen mobile), scope selector, 👍/👎 | 8 | Streamed render; mobile full-screen; feedback persisted |
| D4 | Summarize (page/selection/book) → ephemeral artifact | 5 | Artifact panel with copy/download md+pdf |
| D5 | Extract (user-described) → ephemeral artifact (e.g., table) | 5 | Structured extraction; download |
| D6 | On-the-fly translation fallback (§16.3) — ephemeral, cached | 3 | Missing-locale page offers one-click LLM translation |

### EPIC E — PDF Export *(Phase 4)* — ~18 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| E1 | PDF worker (Playwright/Chromium), print HTML assembler, print CSS | 8 | Page + book/space PDF; Mermaid/KaTeX rendered |
| E2 | Export API: async job, status, signed download URL | 5 | 202+job_id; poll→done+url; expiry |
| E3 | Export UI (page/book/space) + LLM-artifact→PDF; "offline" book PDF | 5 | Buttons wired; downloads correct scope |

### EPIC F — CMS / Authoring *(Phase 5)* — ~42 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| F1 | `<xdocs-admin>` shell + CodeMirror 6 editor + live preview (same renderer) | 8 | Edit/preview parity; admin-only gating |
| F2 | Tree management: CRUD + drag-reorder (spaces/books/pages) | 8 | Reorder persists; move keeps integrity |
| F3 | Drafts → publish (render, embed refresh, reindex) | 5 | Publish triggers pipeline; status transitions |
| F4 | Revision history + diff + restore | 5 | View/restore revisions; optimistic lock conflict prompt |
| F5 | Media manager: upload→object storage, insert, usage | 8 | Image/file upload; signed serve; re-encode images |
| F6 | Admin API surface + permission checks | 8 | All admin endpoints ACL-gated; audited |

### EPIC G — Versions & i18n *(Phase 6)* — ~26 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| G1 | Product versions: visibility flag + pinned default; reader switcher | 8 | Only published versions visible; default lands |
| G2 | Version branching/clone in admin | 5 | Clone v→v'; independent edits |
| G3 | Multilingual content + UI locale bundles + language switcher | 8 | Per-locale content; UI strings localized |
| G4 | LLM-assisted translation drafts + human review workflow | 5 | `llm_draft`→`approved`; override |

### EPIC H — Hardening, Analytics & OSS *(Phase 7)* — ~29 SP
| ID | Story | SP | Key AC |
|---|---|---|---|
| H1 | Analytics: page views/popular + LLM feedback dashboards | 5 | Events captured; admin dashboard |
| H2 | Accessibility audit + fixes (WCAG 2.1 AA, incl. mobile) | 5 | Axe clean; keyboard/SR paths pass |
| H3 | Performance passes (read caching, search latency, bundle size) | 5 | Targets met (Test Plan §7) |
| H4 | Security review + rate limit/CORS/CSP/upload hardening | 5 | Security checklist passed |
| H5 | Helm chart, deploy docs, runbooks | 5 | Clean k8s install on staging |
| H6 | Public docs, examples, license, contribution guide | 4 | OSS-ready repo |

**Total (indicative): ~258 SP** across 8 epics.

---

## 8. Milestones & Sequencing

| Milestone | Contents | Exit criteria |
|---|---|---|
| **M0 — Walking skeleton** | Epic A | Test host renders empty control; JWT flow validated; CI green |
| **M1 — Readable docs (MVP)** | Epic B | Browse + read full content on desktop **and mobile**; theming |
| **M2 — Findable** | Epic C | Hybrid search with scope + ACL |
| **M3 — Intelligent** | Epic D | Ask (RAG+citations), summarize, extract, translation fallback |
| **M4 — Exportable** | Epic E | Page/book/space PDF; offline-as-PDF |
| **M5 — Authorable** | Epic F | Full CMS editing with drafts/revisions/media |
| **M6 — Versioned & multilingual** | Epic G | Product versions + i18n + translation workflow |
| **M7 — Production & OSS** | Epic H | A11y/perf/security gates; Helm; public release |

Dependencies: B depends on A; C depends on B (content+chunks); D depends on C (retrieval); E depends on B render; F depends on B schema; G depends on F; H spans all. Search indexing (C1/C2) and CMS publish (F3) share the same render/embed pipeline — build the pipeline once in B3/C1 and reuse.

---

## 9. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Shadow DOM + Tailwind integration friction | Frontend velocity | Spike in A5; adopt build-time Tailwind→adopted stylesheet; document pattern |
| LLM cost overrun | $$ | Budget guard + rate limits (D1); cache embeddings & retrieval; cap context |
| RAG answer quality / hallucination | Trust | Grounded prompts + citations + "not covered" path; eval harness (Test Plan §6 LLM) |
| pgvector performance at upper scale | Latency | HNSW index, tuned `ef_search`; documented scale-out to dedicated vector store |
| PDF fidelity (Mermaid/KaTeX/tables) | Quality | Render client widgets server-side before print; visual snapshot tests |
| Mobile gesture complexity (drawer/sheet) | UX bugs | Component tests + Playwright emulated-device E2E (B6) |
| Sanitization gaps → stored XSS | Security | Server-side allowlist render; security tests; disable HTML passthrough |
| Scope creep from "full CMS" | Schedule | Phase F gated; non-goals enforced (no real-time collab) |

---

## 10. Definition of Ready / Done

**Definition of Ready (story can start):** clear AC, design reference, test approach noted, dependencies available, estimable.

**Definition of Done (story can merge):**
1. Code + tests written; unit/integration/component pass locally and in CI.
2. Lint, format, type-check clean.
3. E2E smoke updated/passing for affected journeys.
4. **Mobile + a11y** checked for any UI story (responsive at phone/tablet/desktop; keyboard + axe pass).
5. Security-relevant changes covered (authz, sanitization, uploads, rate limits).
6. Docs updated (API spec / README / inline) where behavior changed.
7. PR reviewed and approved; Conventional Commit; squash-merged; CI green.

---

## 11. Traceability

Every story ID (A1…H6) maps to test scenarios in the [Test Cases](../testing/test-cases.md) catalog (same epic letters), which in turn map to the [Test Plan](../testing/test-plan.md) levels and quality gates. The [API Spec](./api-specification.md) and [Data Model](./data-model-and-migrations.md) provide the contract-level detail referenced by backend stories.

---

*End of development plan.*
