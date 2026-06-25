# Xdocs

An **embeddable documentation control** (Web Component) backed by a **Python (FastAPI) micro-service**.

Drop `<xdocs-viewer>` into any web application with a single `<script>` tag to get a
three-pane documentation experience — left page index, center markdown content, right
in-page heading index — plus a master/portal page with search, an LLM "Ask / summarize /
extract" assistant, a full CMS for authoring, multilingual content, and PDF export.

- **Front-end:** pure HTML + Tailwind CSS + vanilla JavaScript (Web Component, Shadow DOM).
- **Backend:** FastAPI + PostgreSQL (markdown in DB) + pgvector, OpenAI/Azure OpenAI, server-side PDF.

## Documentation

- 📐 **[Design Document](docs/design/documentation-control-design.md)** — architecture, data model,
  API surface, components, and a phased delivery plan.

> Status: design phase. The design document is the source of truth for planning development.
