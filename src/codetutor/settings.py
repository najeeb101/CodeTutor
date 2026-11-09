"""Settings that come from the environment (Week 3+). All of them live here.

For local development nothing needs to be set: the defaults point at the database from
compose.yaml (`make db-up`). Real hosting sets DATABASE_URL from a secret.
"""

from __future__ import annotations

import os

DATABASE_URL_ENV = "DATABASE_URL"
TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
SIM_DATABASE_URL_ENV = "SIM_DATABASE_URL"
INSTRUCTOR_TOKEN_ENV = "INSTRUCTOR_TOKEN"
SANDBOX_IMAGE_ENV = "SANDBOX_IMAGE"
SANDBOX_RUNTIME_ENV = "SANDBOX_RUNTIME"
TUTOR_MODEL_ENV = "TUTOR_MODEL"
DEV_LOGIN_ENV = "CODETUTOR_DEV_LOGIN"
TRUSTED_PROXY_HOPS_ENV = "TRUSTED_PROXY_HOPS"
API_DB_PASSWORD_ENV = "API_DB_PASSWORD"
DEMO_DB_PASSWORD_ENV = "DEMO_DB_PASSWORD"
MIN_INSTRUCTOR_TOKEN_CHARS = 16
# The local dev database from compose.yaml: reachable only from this machine, so its password
# is not a secret. Never use it for a real deployment.
DEV_DATABASE_URL = "postgresql://codetutor:codetutor@127.0.0.1:5432/codetutor"
# The tests drop and re-create this database on every run. Same local server, other database.
DEV_TEST_DATABASE_URL = "postgresql://codetutor:codetutor@127.0.0.1:5432/codetutor_test"
# The simulated class (Week 5, `make sim-db` re-creates it). Same server, its own database.
DEV_SIM_DATABASE_URL = "postgresql://codetutor:codetutor@127.0.0.1:5432/codetutor_sim"
# Give up connecting after this long. Without a limit, connecting to a stopped local database
# hung for over 2 minutes (measured 2026-10-02; WSL mirrored networking drops the connection
# attempt instead of refusing it).
DB_CONNECT_TIMEOUT_S = 5


def database_url() -> str:
    """The Postgres URL: $DATABASE_URL if set, else the local dev database."""
    return os.environ.get(DATABASE_URL_ENV) or DEV_DATABASE_URL


def database_url_for_tests() -> str:
    """The database the tests own: $TEST_DATABASE_URL if set, else a local test database.

    It never falls back to $DATABASE_URL on purpose: the tests delete everything in it.
    """
    return os.environ.get(TEST_DATABASE_URL_ENV) or DEV_TEST_DATABASE_URL


def sim_database_url(seed: int = 0) -> str:
    """The simulated class's database: $SIM_DATABASE_URL if set, else a local one.

    Seed 0 uses the name as it is; another seed gets "_s<seed>" (codetutor_sim_s1), so the
    held-out class lives next to the first. Like the tests, it never falls back to
    $DATABASE_URL: `make sim-db` deletes everything in it.
    """
    url = os.environ.get(SIM_DATABASE_URL_ENV) or DEV_SIM_DATABASE_URL
    if seed == 0:
        return url
    base, _, query = url.partition("?")
    return f"{base}_s{seed}" + (f"?{query}" if query else "")


def instructor_token() -> str | None:
    """The shared dev token for /api/instructor/*, or None if the dashboard is switched off.

    Read at every request, so tests and a restart need no special care. A token shorter than
    MIN_INSTRUCTOR_TOKEN_CHARS counts as not set: a short dev token is the one that gets guessed.
    NOT real authentication (docs/api.md §8): one token for all teachers, sent in a header.
    """
    token = os.environ.get(INSTRUCTOR_TOKEN_ENV, "")
    return token if len(token) >= MIN_INSTRUCTOR_TOKEN_CHARS else None


def sandbox_image() -> str | None:
    """The grading image with the runner built in (deploy/sandbox.Dockerfile), or None.

    Set only for a worker that runs in a container (compose.prod.yaml). None means: the pinned
    Python image with runner.py bind-mounted from this machine, as in development and the tests.
    """
    return os.environ.get(SANDBOX_IMAGE_ENV) or None


def dev_login() -> bool:
    """True only if CODETUTOR_DEV_LOGIN=1: the API then also trusts X-User-Id and name logins.

    Off unless switched on (secure by default): `make api` switches it on for local work, the
    production containers never do. NOT secure: anyone can send any id (docs/api.md §2).
    """
    return os.environ.get(DEV_LOGIN_ENV) == "1"


def trusted_proxy_hops() -> int:
    """How many proxies in front of the API append to X-Forwarded-For (api/guards.py).

    0 (the default) ignores the header and uses the socket's address. Set it to exactly the
    number of our own proxies: one more lets a visitor pick their own IP address.
    """
    value = os.environ.get(TRUSTED_PROXY_HOPS_ENV, "0")
    if not value.isdigit():
        raise ValueError(f"{TRUSTED_PROXY_HOPS_ENV} must be a whole number >= 0, not {value!r}")
    return int(value)


def api_db_password() -> str | None:
    """The password of the API's own database role (db/roles.py), or None if not set."""
    return os.environ.get(API_DB_PASSWORD_ENV) or None


def demo_db_password() -> str | None:
    """The password of the read-only demo role (db/roles.py), or None if not set."""
    return os.environ.get(DEMO_DB_PASSWORD_ENV) or None


def sandbox_runtime() -> str | None:
    """The container runtime for grading ("runsc" = gVisor), or None for Docker's default.

    Set on the server (docs/deploy.md): a runtime that Docker does not know makes the worker
    refuse to start instead of falling back to plain Docker (grader/sandbox.py).
    """
    return os.environ.get(SANDBOX_RUNTIME_ENV) or None


def tutor_model() -> str:
    """The hint model, as an `ollama/<model>` spec: $TUTOR_MODEL, else the laptop default.

    On the server it names a small model that runs on the CPU (docs/tutor.md §6).
    """
    from codetutor.tutor.service import TutorConfig  # here, so settings stays import-light

    return os.environ.get(TUTOR_MODEL_ENV) or TutorConfig().model
