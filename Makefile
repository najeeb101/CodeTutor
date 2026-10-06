.PHONY: install lint format db-up db-down db-reset db-migrate db-sync notes-sync worker tutor api web-install web web-check e2e web-e2e sim-db sim-load sim-grade sim-summary sim test test-docker validate build all

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

notes-sync: db-migrate  ## embed the course notes into Postgres for the tutor (needs Ollama)
	uv run python scripts/sync_notes.py

worker: db-sync  ## grade queued submissions in Docker until Ctrl+C (docs/worker.md)
	uv run python scripts/worker.py

tutor: db-sync notes-sync  ## answer queued hint requests with the local model until Ctrl+C (docs/tutor.md §4; needs Ollama)
	uv run python scripts/tutor_worker.py

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

sim-db: db-up  ## DELETE and re-create the simulated class's database codetutor_sim (migrations + problems; Week 5)
	uv run python scripts/sim_cohort.py reset-db

sim-load:  ## queue the simulated class's submissions (lab/sim/cohort-s0.jsonl) in codetutor_sim
	uv run python scripts/sim_cohort.py load

# Four workers share the sim database's queue (FOR UPDATE SKIP LOCKED), each until it is
# empty. The URL comes from settings.py, so it is written in one place only.
SIM_WORKERS ?= 4
sim-grade: db-up  ## grade the simulated class in Docker with SIM_WORKERS (4) workers, then exit
	@url="$$(uv run python -c 'from codetutor.settings import sim_database_url; print(sim_database_url())')"; \
	pids=""; for i in $$(seq $(SIM_WORKERS)); do \
		DATABASE_URL="$$url" uv run python scripts/worker.py --drain & pids="$$pids $$!"; \
	done; status=0; for pid in $$pids; do wait $$pid || status=1; done; exit $$status

sim-summary:  ## compare the simulated class's grades with its labels
	uv run python scripts/sim_cohort.py summary

sim: sim-db sim-load sim-grade sim-summary  ## all four: a fresh, graded simulated class (~15-20 min)

e2e:  ## check the running app end to end over HTTP (needs `make worker`, `make tutor`, `make api`, `make web`)
	uv run python scripts/e2e_check.py

web-e2e: web/node_modules  ## drive the running web UI in headless Chrome (needs the 4 servers; CHROME=... overrides)
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
