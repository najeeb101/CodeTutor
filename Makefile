.PHONY: install lint format db-up db-down db-reset test test-docker validate build all

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

test: db-up  ## run the test suite (without the Docker-sandbox tests); starts the database first
	uv run pytest

test-docker:  ## run the hostile-submission tests in the Docker sandbox (needs Docker)
	uv run pytest -m docker

validate:  ## check every problem in the bank (Week 1, Step 3)
	@if [ -f scripts/validate_problems.py ]; then uv run python scripts/validate_problems.py; \
	else echo "validate: not implemented yet (Step 3)"; fi

build:  ## build dist/problems.jsonl (Week 1, Step 3)
	@if [ -f scripts/build_dataset.py ]; then uv run python scripts/build_dataset.py; \
	else echo "build: not implemented yet (Step 3)"; fi

all: lint test validate
