# Xdocs — Test Case Catalog

**Status:** Draft for execution · **Date:** 2026-06-25
**Companion docs:** [Test Plan](./test-plan.md) · [Development Plan](../development/development-plan.md) · [API Spec](../development/api-specification.md)

Test cases are grouped by epic (A–H) matching the development WBS. Each case: **ID · Title · Level · Preconditions → Steps → Expected**. Levels: U=unit, C=component, I=integration, E=E2E, M=mobile/responsive, S=security, P=performance, L=LLM-quality, A=accessibility.

---

## A — Platform Foundations

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| A-01 | Health & readiness | I | Stack up → GET `/health`, `/ready` → 200; `/ready` reports DB/Redis/storage reachable |
| A-02 | Valid JWT accepted | I/S | Mock-IdP token (reader) → GET `/spaces` → 200 with allowed spaces |
| A-03 | Bad signature rejected | S | Tamper token signature → any API → 401 `invalid_signature` |
| A-04 | Wrong `aud`/`iss` rejected | S | Token with wrong audience → 401 `unauthorized` |
| A-05 | Expired token rejected | S | `exp` in past → 401 `token_expired` |
| A-06 | JWKS rotation | I/S | Rotate mock-IdP key + publish new JWKS → new tokens validate; cache refresh works |
| A-07 | Web Component mounts | C/E | Load test host → `<xdocs-viewer>` upgrades; `xdocs:ready` fires |
| A-08 | Shadow DOM style isolation | C | Host injects aggressive CSS → control layout unaffected; control styles don't leak to host |
| A-09 | Mock-IdP role switcher | E | Switch reader→editor→admin → subsequent token carries new role/scopes |

## B — Content Model & Read Experience (mobile-first)

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| B-01 | List spaces (ACL-filtered) | I/S | reader with `space:sql-server:read` only → GET `/spaces` → returns sql-server, **not** platform |
| B-02 | Nav tree structure | I | GET `/spaces/sql-server/tree?version=2022` → nested books/pages; respects sort_order; lazy `has_children` |
| B-03 | Render page (HTML+headings) | I | GET `/pages/{id}` → sanitized HTML + headings array + prev/next + ETag |
| B-04 | ETag caching | I/P | Repeat GET with `If-None-Match` → 304 |
| B-05 | Markdown features render | C/E | Page with code/Mermaid/KaTeX/admonition/table/image → all render inside shadow root |
| B-06 | Code copy button | C | Click copy → clipboard contains code |
| B-07 | Right TOC scroll-spy | C/E | Scroll content → active heading highlights; click TOC → smooth-scrolls to anchor |
| B-08 | Three-pane → responsive collapse | M | Desktop shows 3 panes; 1024–1280 TOC→popover; tablet nav→drawer |
| B-09 | Mobile swipe nav drawer | M | Phone viewport → swipe from left edge opens drawer with scrim; swipe/tap-scrim closes; focus trapped |
| B-10 | Mobile bottom-sheet TOC | M | Phone → "On this page" opens bottom sheet; snap peek/expanded; scroll-spy preserved |
| B-11 | Container-width breakpoints | M | Embed control in narrow host column on desktop → switches to mobile affordances (ResizeObserver) |
| B-12 | Touch target sizes | M/A | All interactive controls ≥ 44px; `:active` feedback present |
| B-13 | Theming tokens | C/E | Override `--xdocs-color-primary`, set `theme=dark` → colors apply; persists across nav |
| B-14 | Logo slot | C | Provide `slot="logo"` → renders in top bar |
| B-15 | Master page data-driven + curated | E | Master shows auto space cards + a configured curated hero block |
| B-16 | Deep-link navigation events | E | Navigate page → `xdocs:navigate` detail has path/page_id/space/locale/version |
| B-17 | Sanitization (no XSS) | S | Page markdown with `<script>`/`onerror`/`javascript:` → rendered output inert |

## C — Search

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| C-01 | Chunking on publish | I | Publish page → doc_chunks created with anchors; re-publish replaces chunks |
| C-02 | Embeddings generated | I | After publish → chunks have non-null embedding (mock embedder in CI) |
| C-03 | Keyword hit | I | Search exact term → FTS match returned with snippet highlight |
| C-04 | Semantic hit | I | Search paraphrase (no exact words) → relevant page returned via vector |
| C-05 | Hybrid fusion ranking | I | Query matching both → fused ranking; grouped by page; best anchor chosen |
| C-06 | Scope filter | I | `scope=book:{id}` → results limited to that book |
| C-07 | ACL filter in search | S | reader without platform access → platform pages never appear in results |
| C-08 | Type-ahead suggest | I/E | `/search/suggest?q=sel` → title/heading prefixes; UI shows suggestions |
| C-09 | Search UI grouping + mobile | E/M | Results grouped by space/book; sticky search bar reachable on phone |
| C-10 | Zero results | E | Nonsense query → empty state (no error) |

## D — LLM Features

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| D-01 | Provider abstraction switch | U | `LLM_PROVIDER=mock/openai/azure` → adapter selects correct client |
| D-02 | RAG retrieves in scope | I | Ask with `scope=space:sql-server` → retrieved chunks all in scope (mock) |
| D-03 | SSE event sequence | I | POST `/llm/ask` → events `token*` then `citations` then `done`; well-formed |
| D-04 | Citations map to anchors | I/L | Answer citations reference real page/anchor present in retrieval |
| D-05 | "Not covered" path | I/L | Ask question absent from corpus → grounded refusal; empty citations |
| D-06 | Streaming cancellation | I | Client aborts mid-stream → upstream LLM call cancelled; no leak |
| D-07 | Budget guard | I | Exceed monthly budget → 429 `budget_exceeded` |
| D-08 | Rate limit | I/S | Exceed per-user rate → 429 `rate_limited` + `Retry-After` |
| D-09 | Ask panel desktop | E | Ask → streamed answer renders; citations clickable; 👍/👎 records feedback |
| D-10 | Ask panel mobile full-screen | M | Phone → Ask opens full-screen sheet; safe-area respected; streamed render |
| D-11 | Summarize → artifact | I/E | Summarize book → ephemeral artifact; download md + pdf work; expires |
| D-12 | Extract → table | I/E | Extract "params + defaults as table" → markdown table artifact |
| D-13 | Feedback persisted | I | POST `/llm/feedback` up/down → 204; visible in analytics aggregate |
| D-14 | RAG quality (golden set) | L | Nightly golden set → recall@k, citation correctness, faithfulness ≥ thresholds |
| D-15 | Translation fallback (on-the-fly) | I/E | Open `de` page (missing) → served `en` + banner + one-click translate → translated HTML; cached per revision |

## E — PDF Export

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| E-01 | Export single page | I/E | POST `/export {page}` → job → done + signed URL; PDF opens; content matches |
| E-02 | Export book/space | I | Concatenated PDF with cover, TOC, page numbers |
| E-03 | Mermaid/KaTeX in PDF | I/Visual | Diagrams + math render correctly in PDF (visual snapshot) |
| E-04 | Wide content handling | Visual | Code/tables wrap or scale; no clipped content |
| E-05 | Signed URL expiry | I/S | URL expires after TTL → access denied afterward |
| E-06 | LLM artifact → PDF | I | Summary artifact PDF download produces valid file |
| E-07 | Offline = book PDF | E | "Download for offline" yields full book PDF (design §7) |

## F — CMS / Authoring

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| F-01 | Editor live preview parity | C/E | Type markdown → preview matches reader render exactly |
| F-02 | Permission gating | S | reader cannot access admin endpoints/UI (403); editor can |
| F-03 | Create/edit/delete page | I/E | CRUD page → reflected in tree + read API |
| F-04 | Drag-reorder | E | Reorder pages → sort_order persists; tree updates |
| F-05 | Draft not public | I/S | Draft page not returned by reader read/search until published |
| F-06 | Publish pipeline | I | Publish → html_cached set, chunks+embeddings refreshed, searchable |
| F-07 | Revision history + restore | I/E | Edit twice → revisions listed; restore prior → content reverts |
| F-08 | Optimistic lock conflict | I | Two edits with stale `base_revision` → second gets 409 `revision_conflict` |
| F-09 | Media upload + embed | I/E | Upload image → stored; insert into page; serves via signed URL; image re-encoded |
| F-10 | Upload validation | S | Oversize → 413; disallowed type → 422; no path injection |
| F-11 | Orphan media cleanup | I | Unreferenced asset removed by worker; referenced asset retained |

## G — Versions & i18n

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| G-01 | Version visibility | I/S | `internal` version not shown to readers; `published` is |
| G-02 | Pinned default version | I/E | Reader lands on space default version |
| G-03 | Version switcher | E | Switch 2019↔2022 → content/tree change accordingly |
| G-04 | Version clone | I | Clone version → independent copy; edits don't affect source |
| G-05 | Multilingual content | I/E | `fr` page returns French content; switcher lists available locales |
| G-06 | UI locale strings | E/M | Set `locale=fr` → control chrome localized |
| G-07 | LLM translation draft workflow | I | Generate draft → `llm_draft`; approve → `approved`; override edits saved |
| G-08 | Missing-locale fallback policy | I/E | `de` missing → source + banner + auto-translate offer (ties to D-15) |

## H — Hardening, Analytics & OSS

| ID | Title | Lvl | Preconditions → Steps → Expected |
|---|---|---|---|
| H-01 | Page-view analytics | I | View pages → counts recorded; popular list reflects |
| H-02 | LLM feedback dashboard | I/E | 👍/👎 aggregates render in admin analytics |
| H-03 | Search analytics deferred | I | `search` event type exists in schema but capture disabled in v1 (§16.7) |
| H-04 | Accessibility audit | A | axe on viewer/master/admin → no violations; keyboard-only journey completes; SR labels correct |
| H-05 | Mobile a11y | A/M | Focus trap in drawer/sheet/Ask; SR open/close announced; text scaling |
| H-06 | Read latency | P | p95 cached < 200 ms / uncached < 500 ms at target scale |
| H-07 | Search latency | P | p95 < 600 ms |
| H-08 | Bundle size | P | Reader core gzipped < ~150 KB; heavy libs lazy-loaded |
| H-09 | Lighthouse mobile | P/A | perf/a11y/best-practices ≥ 90 |
| H-10 | ACL isolation matrix | S | Full role×space matrix → only permitted data across all endpoints |
| H-11 | ZAP baseline | S | No high-severity findings on staging |
| H-12 | Dependency/secret scans | S | pip/npm audit + secret scan clean (no high sev) |
| H-13 | Helm install | I | Fresh k8s install via Helm on staging → all services healthy |
| H-14 | Contract conformance | Contract | Running API conforms to API Spec (schemas/errors/SSE) |

---

## Cross-cutting: Integration smoke (E2E suite, runs per-PR)

| ID | Journey |
|---|---|
| SMOKE-1 | Load test host → browse tree → open page (rich markdown renders) |
| SMOKE-2 | Search → open result → right TOC scroll-spy |
| SMOKE-3 | Ask a question → streamed answer + citation click |
| SMOKE-4 | Export current page → download PDF |
| SMOKE-5 | (mobile viewport) swipe drawer → open page → bottom-sheet TOC → full-screen Ask |
| SMOKE-6 | (editor) edit page → preview → publish → see change in reader |

---

## Traceability Matrix (story → cases)

| Epic stories | Test cases |
|---|---|
| A1–A6 | A-01…A-09, SMOKE-1 |
| B1–B8 | B-01…B-17, SMOKE-1/2/5 |
| C1–C5 | C-01…C-10, SMOKE-2 |
| D1–D6 | D-01…D-15, SMOKE-3 |
| E1–E3 | E-01…E-07, SMOKE-4 |
| F1–F6 | F-01…F-11, SMOKE-6 |
| G1–G4 | G-01…G-08 |
| H1–H6 | H-01…H-14, SMOKE-5 |

Every WBS story has ≥1 mapped scenario; every scenario maps to a [Test Plan](./test-plan.md) level and quality gate.

---

*End of test case catalog.*
