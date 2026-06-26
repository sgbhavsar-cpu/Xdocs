# Xdocs

An **embeddable documentation control** (Web Component) backed by a **Python (FastAPI) micro-service**.

Drop `<xdocs-viewer>` into any web application with a single `<script>` tag to get a
three-pane documentation experience — left page index, center markdown content, right
in-page heading index — plus a master/portal page with search, an LLM "Ask / summarize /
extract" assistant, a full CMS for authoring, multilingual content, and PDF export.

- **Front-end:** pure HTML + Tailwind CSS + vanilla JavaScript (Web Component, Shadow DOM).
- **Backend:** FastAPI + PostgreSQL (markdown in DB) + pgvector, OpenAI/Azure OpenAI, server-side PDF.

## Features

- **Reader** (`<xdocs-viewer>`): three-pane layout (nav · content · TOC with scroll-spy),
  fully responsive with a mobile nav drawer + bottom-sheet TOC, light/dark theming, code
  highlighting / Mermaid / KaTeX (lazy-loaded), version + language switchers, localized UI.
- **Portal** (`<xdocs-master>`): data-driven space cards + global search.
- **Search**: hybrid keyword + semantic (RRF fusion), scope + ACL filtering, highlighted
  snippets, deep-link to section.
- **Ask** (RAG): streamed answers (SSE) with citations, scope selector, 👍/👎 feedback;
  summarize & extract → downloadable artifacts; on-the-fly translation fallback.
- **Export**: server-side PDF (page / book / space / artifact) via headless Chromium.
- **CMS** (`<xdocs-admin>`): markdown editor with live preview, draft → publish (re-render +
  re-index), revision history + restore, optimistic locking, media uploads, product-version
  branching, and LLM-assisted translation draft → approve.
- **Hardening**: host-issued JWT auth (JWKS) + per-space ACLs, rate limits + LLM budget guard,
  ETag caching, security headers, analytics (popular pages + answer feedback).

## Quick start

### Option A — VS Code Dev Container (one click, great on Windows)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop), [VS Code](https://code.visualstudio.com), and the **Dev Containers** extension.
2. `git clone https://github.com/sgbhavsar-cpu/Xdocs.git` and open the folder in VS Code.
3. Run **“Dev Containers: Reopen in Container”** (command palette, `F1`).

The container installs deps, builds the front-end, starts the stack, and seeds demo
content. When it finishes, open **http://localhost:8080** (API docs at `:8000/docs`).
To debug the API with breakpoints: `docker compose stop api`, then press `F5`.

### Option B — Docker Compose

```bash
cp .env.example .env             # defaults use mock LLM + mock PDF (offline)
docker compose up --build        # api, postgres(pgvector), redis, minio, test-host
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.scripts.seed
make fe-build                    # build the control bundles (or: cd frontend && pnpm i && pnpm build)
open http://localhost:8080       # demo host (portal → viewer → admin)
```

Embed in any app:

```html
<script type="module" src="https://cdn.example.com/xdocs/xdocs.js"></script>
<xdocs-viewer base-url="https://docs-api.example.com" space="sql-server" theme="auto"></xdocs-viewer>
<script>
  document.querySelector('xdocs-viewer').tokenProvider = () => myApp.getDocsToken();
</script>
```

## Status

Implemented through Milestone **M7**: reader, portal, search, LLM features, PDF export, CMS,
versions/i18n, and hardening — backend + frontend, with automated tests (pytest + vitest)
and a Dockerized dev stack. The LLM and PDF renderers default to deterministic mocks so
everything runs offline; set `LLM_PROVIDER=openai` / `PDF_RENDERER=chromium` for production.

See **[CONTRIBUTING.md](CONTRIBUTING.md)** to develop locally and **[deploy/helm](deploy/helm)**
for the Kubernetes chart.

## Documentation

**Design**
- 📐 **[Design Document](docs/design/documentation-control-design.md)** — architecture, data model,
  API surface, components, decisions, and a phased delivery plan.

**Development**
- 🛠️ **[Development Plan](docs/development/development-plan.md)** — work breakdown (epics/stories), milestones, environment setup, standards, CI/CD, Definition of Done.
- 🔌 **[API Specification](docs/development/api-specification.md)** — REST/SSE contract: endpoints, schemas, errors, auth.
- 🗄️ **[Data Model & Migrations](docs/development/data-model-and-migrations.md)** — tables, indexes, migration order, seed data.

**Testing**
- ✅ **[Test Plan & Strategy](docs/testing/test-plan.md)** — levels, tooling, environments, quality gates, mobile/security/LLM focus.
- 🧪 **[Test Case Catalog](docs/testing/test-cases.md)** — detailed scenarios per epic + traceability matrix.

**Contributing & deploy**
- 🤝 **[CONTRIBUTING.md](CONTRIBUTING.md)** — dev setup, conventions, Definition of Done.
- ☸️ **[deploy/helm](deploy/helm)** — Kubernetes Helm chart.

> The design/development/testing docs are the source of truth; the design doc records the
> v1 implementation decisions (e.g. app-level search vs the pgvector scale-out path).
