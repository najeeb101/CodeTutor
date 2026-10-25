.PHONY: rl-train rl-train-c rl-after-run rl-after-report rl-folds-report rl-noise-run rl-noise-report rl-pool-run rl-pool-report rl-seed-run rl-seed-report rl-hacking rl-smoke rl-baseline-run rl-baseline-report rl-reward-bench rl-data rl-install rl-env skill install lint format db-up db-down db-reset db-migrate db-sync notes-sync worker tutor api web-install web web-check e2e web-e2e sim-db sim-load sim-grade sim-summary sim integrity test test-docker validate build all

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

# Which simulated class: 0 = codetutor_sim (thresholds are chosen on it), 1 = codetutor_sim_s1
# (the held-out class the integrity report is measured on). `SIM_SEED=1 make sim`.
SIM_SEED ?= 0
sim-db: db-up  ## DELETE and re-create the simulated class's database (SIM_SEED=0: codetutor_sim; Week 5)
	uv run python scripts/sim_cohort.py reset-db --seed $(SIM_SEED)

sim-load:  ## queue the simulated class's submissions (lab/sim/cohort-s$(SIM_SEED).jsonl) in its database
	uv run python scripts/sim_cohort.py load --seed $(SIM_SEED)

# Four workers share the sim database's queue (FOR UPDATE SKIP LOCKED), each until it is
# empty. The URL comes from settings.py, so it is written in one place only.
SIM_WORKERS ?= 4
sim-grade: db-up  ## grade the simulated class in Docker with SIM_WORKERS (4) workers, then exit
	@url="$$(uv run python -c 'from codetutor.settings import sim_database_url; print(sim_database_url($(SIM_SEED)))')"; \
	pids=""; for i in $$(seq $(SIM_WORKERS)); do \
		DATABASE_URL="$$url" uv run python scripts/worker.py --drain & pids="$$pids $$!"; \
	done; status=0; for pid in $$pids; do wait $$pid || status=1; done; exit $$status

sim-summary:  ## compare the simulated class's grades with its labels
	uv run python scripts/sim_cohort.py summary --seed $(SIM_SEED)

sim: sim-db sim-load sim-grade sim-summary  ## all four: a fresh, graded simulated class (~15-20 min)

# Week 5 Step 2b: the integrity checks as a batch job over both graded simulated classes
# (`make sim` and `SIM_SEED=1 make sim` first). Replaces each database's integrity_flags, then
# (Step 2c) writes lab/integrity/reports/integrity.md: thresholds chosen on seed 0, measured on 1.
integrity: db-up  ## run the integrity checks on both simulated classes + write the held-out report
	uv run python scripts/integrity.py run --seed 0
	uv run python scripts/integrity.py run --seed 1
	uv run python scripts/integrity.py report

# Week 5 Step 3: difficulty and skill estimates (pass rates + Rasch) scored against the sim's truth.
skill: db-up  ## write lab/skill/reports/skill.md from both graded simulated classes (~25 s)
	uv run python scripts/skill.py report

e2e:  ## check the running app end to end over HTTP (needs `make worker`, `make tutor`, `make api`, `make web`)
	uv run python scripts/e2e_check.py

web-e2e: web/node_modules  ## drive the running web UI in headless Chrome (needs the 4 servers; CHROME=... overrides)
	cd web && npm run e2e

test: db-up  ## run the test suite (without the Docker and slow tests); starts the database first
	uv run pytest

# Week 6 (RL training). The `rl` dependency group (torch, transformers, trl, peft, ...) is not part
# of `make install`: a plain `uv sync` is exact and should remove it again (not tried); `rl-install` puts it back.
rl-install:  ## install the training packages too (uv sync --group rl; ~5.6 GB)
	uv sync --group rl

rl-data:  ## build the RL prompt files: 4 module folds into dist/rl/ + lab/rl/splits.json (no GPU needed)
	uv run python scripts/rl_dataset.py build

rl-reward-bench:  ## check the RL reward against the stored Week 2 grades and time it (needs Docker, ~5 min)
	uv run python scripts/rl_reward_bench.py

rl-baseline-run:  ## the 'before' baseline: 0.5B and 1.5B on all 33 problems, n=10 (GPU + Docker, ~1 h, resumable)
	uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-0.5b-bf16-t0.8-n10.yaml
	uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-1.5b-bf16-t0.8-n10.yaml

rl-baseline-report:  ## lab/rl/reports/baseline.md from the committed results (no GPU)
	uv run python scripts/rl_baseline.py report

RUN ?= smoke
MODE ?= partial
STEPS ?= 30
rl-smoke:  ## GRPO smoke run on the 0.5B (GPU + Docker; make rl-smoke RUN=x MODE=partial|all_or_nothing STEPS=30)
	uv run --group rl python scripts/rl_train.py --run-id $(RUN) --mode $(MODE) --steps $(STEPS)

FOLD ?= c
SEED ?= 0
RUN ?= $(FOLD)
rl-train:  ## Steps 5-6: the real GRPO run, 100 steps x 4 prompts (~2 h; GPU + Docker; make rl-train FOLD=a|b|c|d [SEED=1] [RESUME=--resume])
	uv run --group rl python scripts/rl_train.py --run-id fold-$(if $(filter-out 0,$(SEED)),$(FOLD)-s$(SEED),$(FOLD)) --fold $(FOLD) --seed $(SEED) --steps 100 --prompts-per-step 4 --only-mixed --save-steps 25 $(RESUME)

rl-train-c:  ## Step 5 command, kept: same as make rl-train FOLD=c
	$(MAKE) rl-train FOLD=c

rl-after-run:  ## Steps 5-6: the 'after' eval of one adapter (make rl-after-run RUN=a|b|c|d|c-s1; GPU + Docker, ~15 min, resumable)
	uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-0.5b-grpo-$(RUN)-t0.8-n10.yaml

rl-after-report:  ## lab/rl/reports/fold-<FOLD>.md from the committed results (no GPU)
	uv run python scripts/rl_after.py report --fold $(FOLD)

rl-folds-report:  ## lab/rl/reports/folds.md: every trained run together (no GPU; needs folds a-d, c-s1 is optional)
	uv run python scripts/rl_after.py report-all

rl-noise-run:  ## Week 7 Step 1: re-run the baseline and the c and b adapters with another sampling draw (GPU + Docker, ~45 min, resumable)
	for n in bf16 grpo-c grpo-b; do uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-0.5b-$$n-t0.8-n10-s1000.yaml || exit 1; done

rl-noise-report:  ## lab/rl/reports/noise.md from the committed results (no GPU)
	uv run python scripts/rl_after.py noise

POOL_RUNS = bf16-t0.8-n10-s2000 grpo-c-t0.8-n10-s2000 grpo-b-t0.8-n10-s2000 grpo-a-t0.8-n10-s1000 grpo-a-t0.8-n10-s2000 grpo-d-t0.8-n10-s1000 grpo-d-t0.8-n10-s2000
rl-pool-run:  ## Week 7 Step 2a: the 7 missing sampling draws, so every model has draws 0, 1000, 2000 (GPU + Docker, ~1.75 h, resumable)
	for n in $(POOL_RUNS); do uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-0.5b-$$n.yaml || exit 1; done

rl-pool-report:  ## lab/rl/reports/pooled.md: 30 answers per problem (no GPU)
	uv run python scripts/rl_after.py pooled

rl-seed-run:  ## Week 7 Step 2b: the 3 sampling draws of the fold-c adapter trained with seed 1 (GPU + Docker, ~45 min, resumable)
	for n in grpo-c-s1-t0.8-n10 grpo-c-s1-t0.8-n10-s1000 grpo-c-s1-t0.8-n10-s2000; do uv run --group rl python scripts/run_eval.py lab/evals/configs/hf-qwen2.5-coder-0.5b-$$n.yaml || exit 1; done

rl-seed-report:  ## lab/rl/reports/seeds.md: fold c, two training seeds (no GPU)
	uv run python scripts/rl_after.py seeds

rl-hacking:  ## lab/rl/reports/hacking.md: reward-hacking audit of the stored answers (no GPU)
	uv run python scripts/rl_hacking_audit.py report

rl-env:  ## check the GPU, the model and the grader for training (needs rl-install, Docker, internet once)
	uv run --group rl python scripts/rl_env_check.py

test-docker: db-up  ## run the hostile-submission and worker tests in the Docker sandbox (needs Docker)
	uv run pytest -m docker

validate:  ## check every problem in the bank (Week 1, Step 3)
	@if [ -f scripts/validate_problems.py ]; then uv run python scripts/validate_problems.py; \
	else echo "validate: not implemented yet (Step 3)"; fi

build:  ## build dist/problems.jsonl (Week 1, Step 3)
	@if [ -f scripts/build_dataset.py ]; then uv run python scripts/build_dataset.py; \
	else echo "build: not implemented yet (Step 3)"; fi

all: lint test validate
