.PHONY: install lint format db-up db-down db-reset db-migrate db-sync worker api web-install web web-check e2e web-e2e test test-docker validate build all

install:  ## install deps + editable package (uv sync installs the project in editable mode)
	uv sync

lint:  ## ruff check + format check (no changes made)
	uv run ruff check .
	uv run ruff format --check .

format:  ## auto-format code
	uv run ruff format .

db-up:  ## start the local Postgres (compose.yaml) and wait until it is healthy (needs Docker)
	docker compose up -d --wait db

db-down:  ## stop the local Postgres (the data is kept)
	docker compose down

db-reset:  ## stop the local Postgres AND delete its data (dev only)
	docker compose down -v

db-migrate: db-up  ## create/upgrade the tables (Alembic migrations, docs/database.md)
	uv run alembic upgrade head

db-sync: db-migrate  ## copy the problem folders into Postgres (safe to run again)
	uv run python scripts/sync_problems.py

worker: db-sync  ## grade queued submissions in Docker until Ctrl+C (docs/worker.md)
	uv run python scripts/worker.py

api: db-sync  ## run the HTTP API on http://127.0.0.1:8000 until Ctrl+C (docs/api.md; dev login, not secure)
	uv run uvicorn codetutor.api.app:create_app --factory --host 127.0.0.1 --port 8000

web-install:  ## install the web UI's npm packages from package-lock.json (needs Node 24, nvm)
	cd web && npm ci

web: web/node_modules  ## run the web UI on http://localhost:3100 (WEB_PORT overrides; needs `make api`)
	cd web && npm run dev

web-check:  ## type-check and build the web UI (production build)
	cd web && npm run build

web/node_modules:
	cd web && npm ci

e2e:  ## check the running app end to end over HTTP (needs `make worker`, `make api`, `make web`)
	uv run python scripts/e2e_check.py

web-e2e: web/node_modules  ## drive the running web UI in headless Chrome (needs the 3 servers; CHROME=... overrides)
	cd web && npm run e2e

test: db-up  ## run the test suite (without the Docker and slow tests); starts the database first
	uv run pytest

test-docker: db-up  ## run the hostile-submission and worker tests in the Docker sandbox (needs Docker)
	uv run pytest -m docker

validate:  ## check every problem in the bank (Week 1, Step 3)
	@if [ -f scripts/validate_problems.py ]; then uv run python scripts/validate_problems.py; \
	else echo "validate: not implemented yet (Step 3)"; fi

build:  ## build dist/problems.jsonl (Week 1, Step 3)
	@if [ -f scripts/build_dataset.py ]; then uv run python scripts/build_dataset.py; \
	else echo "build: not implemented yet (Step 3)"; fi

all: lint test validate
