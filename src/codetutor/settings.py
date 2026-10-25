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
