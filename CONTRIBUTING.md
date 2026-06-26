# Contributing to Xdocs

Thanks for your interest in contributing! Xdocs is MIT-licensed and welcomes
issues and pull requests.

## Project layout

| Path | What |
|---|---|
| `backend/` | FastAPI service (Python 3.12) |
| `frontend/` | Web Components (`xdocs`, `xdocs-master`, `xdocs-admin`) |
| `examples/test-host/` | Demo host page + mock IdP |
| `deploy/` | Docker, Compose, Helm |
| `docs/` | Design, development, and testing docs |

## Getting started

```bash
cp .env.example .env          # set keys (or keep LLM_PROVIDER=mock / PDF_RENDERER=mock)
docker compose up --build     # api, postgres(pgvector), redis, minio, test-host
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.scripts.seed
make fe-build                 # build the control bundles
# open http://localhost:8080
```

## Development loop

**Backend**
```bash
cd backend && pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy app && pytest -q
```

**Frontend**
```bash
cd frontend && pnpm install
pnpm lint && pnpm test && pnpm build
```

## Conventions

- **Commits**: Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:` …).
- **Python**: ruff (lint + format) + mypy; async SQLAlchemy 2.0; service layer holds
  logic, routers stay thin.
- **JS/CSS**: vanilla JS (no SPA framework in the reader); prettier + eslint; types via
  JSDoc where helpful. Heavy libs (Mermaid/KaTeX/highlight.js) are lazy-loaded.
- **Tests**: add/extend tests with every change. Backend uses pytest against SQLite
  fixtures; frontend uses vitest (jsdom). Keep the suite green and offline (the LLM and
  PDF renderers default to deterministic mocks).

## Definition of Done

See [docs/development/development-plan.md §10](docs/development/development-plan.md).
Briefly: tests + lint + types pass, mobile/a11y checked for UI changes, security-relevant
paths covered, docs updated, PR reviewed, CI green.

## Reporting security issues

Please do not open public issues for security vulnerabilities — contact the maintainers
privately first.
