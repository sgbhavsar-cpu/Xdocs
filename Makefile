.PHONY: help up down logs migrate seed fe-build fe-dev be-test fe-test lint fmt

help:
	@echo "Xdocs dev targets:"
	@echo "  up         - build & start the full dev stack (compose)"
	@echo "  down       - stop the stack"
	@echo "  migrate    - run alembic migrations inside the api container"
	@echo "  fe-build   - build the frontend bundles (xdocs.js)"
	@echo "  fe-dev     - watch-build the frontend"
	@echo "  be-test    - run backend tests"
	@echo "  fe-test    - run frontend tests"
	@echo "  lint       - run linters (ruff + eslint)"
	@echo "  fmt        - format (ruff format + prettier)"

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f api

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python -m app.scripts.seed

fe-build:
	cd frontend && pnpm install && pnpm build

fe-dev:
	cd frontend && pnpm dev

be-test:
	cd backend && pytest -q

fe-test:
	cd frontend && pnpm test

lint:
	cd backend && ruff check . && mypy app
	cd frontend && pnpm lint

fmt:
	cd backend && ruff format .
	cd frontend && pnpm format
