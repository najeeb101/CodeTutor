"""Settings that come from the environment (Week 3+). All of them live here.

For local development nothing needs to be set: the defaults point at the database from
compose.yaml (`make db-up`). Real hosting sets DATABASE_URL from a secret.
"""

from __future__ import annotations

import os

DATABASE_URL_ENV = "DATABASE_URL"
# The local dev database from compose.yaml: reachable only from this machine, so its password
# is not a secret. Never use it for a real deployment.
DEV_DATABASE_URL = "postgresql://codetutor:codetutor@127.0.0.1:5432/codetutor"


def database_url() -> str:
    """The Postgres URL: $DATABASE_URL if set, else the local dev database."""
    return os.environ.get(DATABASE_URL_ENV) or DEV_DATABASE_URL
