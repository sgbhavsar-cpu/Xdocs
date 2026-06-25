# Xdocs

An **embeddable documentation control** (Web Component) backed by a **Python (FastAPI) micro-service**.

Drop `<xdocs-viewer>` into any web application with a single `<script>` tag to get a
three-pane documentation experience — left page index, center markdown content, right
in-page heading index — plus a master/portal page with search, an LLM "Ask / summarize /
extract" assistant, a full CMS for authoring, multilingual content, and PDF export.

- **Front-end:** pure HTML + Tailwind CSS + vanilla JavaScript (Web Component, Shadow DOM).
- **Backend:** FastAPI + PostgreSQL (markdown in DB) + pgvector, OpenAI/Azure OpenAI, server-side PDF.

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

> Status: planning phase. These documents are the source of truth for building Xdocs.
