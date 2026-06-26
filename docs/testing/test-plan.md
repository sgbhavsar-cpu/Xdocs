# Xdocs — Test Plan & Strategy

**Status:** Draft for execution · **Date:** 2026-06-25
**Companion docs:** [Design](../design/documentation-control-design.md) · [Development Plan](../development/development-plan.md) · [Test Cases](./test-cases.md)

---

## 1. Objectives

Verify that Xdocs is **correct, secure, accessible, and fully mobile-compatible**, and that the embeddable control integrates into an arbitrary host via the host-issued-token flow. Testing is **risk-based** (auth, ACL isolation, sanitization, RAG grounding, mobile UX, and PDF fidelity get the most attention) and **automated-first** (everything that can run in CI does).

---

## 2. Scope

**In scope:** reader control (viewer + master), admin/CMS, host SDK, backend API + workers, search, LLM features, PDF export, i18n/versions, theming, analytics, the test/demo host, and deployment artifacts.

**Out of scope (v1):** PWA/offline service-worker behavior and native apps (not built — design non-goals); real-time collaborative editing; load testing beyond the small–mid target (< 10k pages, < 500 concurrent).

---

## 3. Test Levels & Types

| Level / Type | What it covers | Primary tools |
|---|---|---|
| **Unit (backend)** | services, render/sanitize, chunking, fusion math, permission mapping, provider adapter (mocked LLM) | pytest, pytest-asyncio |
| **Unit/Component (frontend)** | Web Component logic, render enhancers, drawer/sheet/TOC behavior, theming | vitest, @web/test-runner / jsdom |
| **Integration (backend)** | API endpoints against real Postgres+pgvector+Redis+MinIO; migrations; workers | pytest + httpx.AsyncClient, testcontainers/compose |
| **Contract** | implementation matches [API Spec](../development/api-specification.md) (schemas, errors, SSE shape) | schemathesis / OpenAPI diff |
| **E2E (web)** | full user journeys through the test host against the running stack | Playwright |
| **Responsive / Mobile** | phone/tablet/desktop layouts, swipe drawer, bottom-sheet TOC, full-screen Ask, sticky search, touch targets | Playwright emulated devices |
| **Visual regression** | rendered markdown, themes, PDF pages | Playwright snapshots / pixel diff |
| **Accessibility** | WCAG 2.1 AA, keyboard, screen-reader semantics, mobile a11y | axe-core, Playwright + manual SR pass |
| **Performance** | read/search latency, SSE first-token, bundle size, PDF time | k6/Locust, Lighthouse, custom timers |
| **Security** | authz/ACL isolation, sanitization/XSS, upload validation, rate limits, dependency/secret scans | ZAP baseline, bandit, npm/pip audit, custom authz tests |
| **LLM / RAG quality** | grounding, citation correctness, "not covered" behavior, regression of answers | offline eval harness (golden Q/A set) |

---

## 4. Test Environments

| Env | Purpose | Composition |
|---|---|---|
| **Local** | dev TDD loop | `docker compose` full stack + test host; seeded data |
| **CI** | gate every PR | ephemeral services (Postgres/pgvector, Redis, MinIO), mock LLM, headless Playwright |
| **Staging** | pre-release, manual + smoke | k8s via Helm; real LLM (test keys) with budget cap; anonymized seed |
| **LLM mock vs live** | default mock provider in unit/integration/E2E for determinism & cost; a small **live-LLM nightly** suite validates real provider wiring | provider flag `LLM_PROVIDER=mock` |

---

## 5. Test Data & Fixtures

- The **seed dataset** (Data Model §7) is the canonical fixture: multi-space, multi-version (published + internal), nested pages, rich markdown, `en`/partial-`fr`/missing-`de` locales, role ACLs.
- Backend integration tests use factories + transactional rollback per test.
- The **mock-IdP** issues tokens per role (reader/editor/admin) and per space scope so ACL isolation is testable.
- A **golden RAG set** (~30–50 Q→expected-source-anchor pairs) anchors LLM quality tests.

---

## 6. Special Focus: LLM / RAG Testing

Because LLM output is non-deterministic, the strategy separates **plumbing** from **quality**:

1. **Plumbing (deterministic, in CI):** with a **mock provider**, assert retrieval selects the right chunks in scope, the prompt is grounded (contains retrieved context), SSE event sequence is correct (`token*`→`citations`→`done`), citations map to real anchors, cancellation aborts upstream, and budget/rate-limit guards trigger `429`.
2. **Quality (live, nightly/offline):** run the golden set against the real model; score **retrieval recall@k**, **citation correctness** (cited anchor actually supports the answer), **grounding/faithfulness** (no claims outside context — LLM-as-judge + spot checks), and **"not covered" precision** (refuses when answer absent). Track scores over time; a regression beyond threshold fails the nightly and blocks release.
3. **Cost guardrails:** assert budget guard and per-user rate limits in integration tests; track token usage in nightly.

---

## 7. Performance Targets (quality gates)

| Metric | Target |
|---|---|
| Page read (cached) p95 | < 200 ms |
| Page read (uncached) p95 | < 500 ms |
| Search p95 | < 600 ms |
| Ask SSE first token | < 2 s typical |
| Reader bundle (`xdocs.js`, gzipped) | < ~150 KB core (libs lazy-loaded) |
| PDF (single page) | < 5 s; (book) reasonable, async |
| Lighthouse mobile (perf/a11y/best-practices) | ≥ 90 |

Measured on staging with seeded data at target scale; regressions fail the perf gate.

---

## 8. Quality Gates (CI enforcement)

A PR cannot merge unless:
1. Lint + format + type-check clean (ruff/mypy; eslint/prettier/tsc-checkJs).
2. Unit + integration + component tests pass.
3. **Coverage:** backend ≥ 85% lines on changed modules; frontend ≥ 80% on changed components (overall trend non-decreasing).
4. Contract tests pass against the API Spec.
5. E2E **smoke** suite green (core journeys, incl. one mobile viewport).
6. Security static scans (bandit, deps audit, secret scan) — no high severity.
7. Accessibility checks (axe) — no new violations on touched UI.

Nightly (not per-PR): full E2E matrix across devices, visual regression, live-LLM quality, ZAP baseline, performance.

---

## 9. Mobile / Responsive Testing (explicit)

Since full mobile compatibility is a v1 requirement (design §3.2.1):
- Playwright device matrix: **iPhone (small), Pixel, iPad, desktop**; portrait + landscape for key journeys.
- Verify: swipe-open/close nav drawer with scrim + focus trap; bottom-sheet TOC snap points + scroll-spy; full-screen Ask panel + safe-area insets; sticky search reachable; ≥44px tap targets; code horizontal-scroll/wrap toggle; wide-table scroll; Mermaid zoom.
- **Container-width** behavior: embed the control in a deliberately narrow host column and assert it switches to mobile affordances via `ResizeObserver` (not just viewport).
- Touch-event tests for gestures; reduced-motion honored.

---

## 10. Security Testing (explicit)

- **ACL isolation matrix:** for each role/scope, assert read/search/LLM/export/admin endpoints return only permitted spaces; attempt cross-space access → 403. No data leakage via search or RAG retrieval.
- **AuthN:** expired/forged/wrong-`aud`/wrong-`iss` tokens rejected; JWKS rotation handled.
- **Sanitization/XSS:** malicious markdown (script, event handlers, `javascript:` URLs, SVG payloads) is neutralized server-side; rendered HTML in viewer and PDF is safe.
- **Uploads:** type/size enforced; images re-encoded; path/key injection prevented; serving via signed URLs.
- **Rate limits & budget:** verified to trigger and recover.
- **Transport/headers:** CORS allowlist, CSP guidance, no secrets in client bundle.

---

## 11. Defect Management

- Severity: **S1** (security/data-loss/blocked core journey) → fix before release; **S2** (major feature broken) → fix in milestone; **S3** (minor/cosmetic) → backlog.
- Every fixed bug adds a regression test reproducing it.
- Flaky tests are quarantined + ticketed, not ignored.

---

## 12. Entry / Exit Criteria (per milestone)

**Entry:** stories meet Definition of Ready; environment + fixtures available.
**Exit (release of a milestone):**
- All planned test cases for the milestone executed; S1/S2 = 0 open.
- Quality gates (§8) green; performance (§7) and a11y targets met for shipped UI.
- For M3 (LLM): RAG quality scores above thresholds.
- For M1+ UI: mobile/responsive matrix green.
- Docs (API/README) updated; release notes drafted.

---

## 13. Roles & Responsibilities

- **Engineers:** write unit/integration/component tests with their code (TDD encouraged); keep CI green.
- **Reviewer:** confirms test coverage + DoD on PR.
- **Owner/QA hat (rotating):** maintains E2E suite, golden RAG set, performs exploratory + manual SR/mobile passes per milestone, signs off exit criteria.

---

## 14. Traceability

Test scenarios in [Test Cases](./test-cases.md) are keyed by epic (A–H) matching the [Development Plan](../development/development-plan.md) WBS, and reference the [API Spec](../development/api-specification.md) endpoints they exercise. Every story has at least one mapped scenario; every quality gate above maps to an automated suite in CI.

---

*End of test plan.*
