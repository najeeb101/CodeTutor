# syntax=docker/dockerfile:1
# The Python image. One image, four roles (compose.prod.yaml picks the command):
#   migrate (alembic + problem sync, then exit), api (uvicorn), worker (grading), tutor (hints).
# Every base image is pinned by digest and exists for amd64 and arm64 (the Oracle server is ARM).

FROM ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 AS uv
# Only the `docker` program is taken from this image: the worker starts the grading containers.
FROM docker:29.9.1-cli@sha256:6fae2214c3121a28d5aa639d09032f61310b7c9c75ffbad1025f261a1b621800 AS dockercli

# The same Python as the grading image (grader/sandbox.py DOCKER_IMAGE).
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    DOCKER_CONFIG=/tmp/.docker

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /app

# Packages first, in their own layer: it is rebuilt only when uv.lock changes, not on every
# code change. uv itself is only mounted for this step, so it is not in the final image.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-dev --no-install-project

# The code keeps the repository layout: the problems folder is found next to src/ (loader.py).
COPY src ./src
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --locked --no-dev
COPY alembic.ini ./
COPY problems ./problems
COPY course ./course
# The simulated classes (cohort files) for the public demo's seeding (docs/deploy.md).
COPY lab/sim ./lab/sim
# The 7B model's answers: the integrity job's "known AI answers" (integrity/known_ai.py).
COPY lab/evals/results/qwen2.5-coder-7b-q4-t0.8-n10.jsonl ./lab/evals/results/
COPY scripts ./scripts

# Not root. The files above stay owned by root, so this user can't change the code.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
USER app

CMD ["python", "-c", "print('codetutor-app: pick a role, see compose.prod.yaml')"]
