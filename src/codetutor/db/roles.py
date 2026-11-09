"""The API's own database role (Deploy Step 2a): least privilege, enforced by Postgres.

The API never needs the sealed problem copies (hidden tests, solutions), the course-note
vectors, or the tutor's trace (blocked attempts may contain solution code). Until now only a
source-scan test kept it away from them. With this role, Postgres itself answers "permission
denied", even if an API bug or an injected query tried. The workers keep the owner role: they
must read the sealed copies.

Roles belong to the whole Postgres server; the grants belong to one database. `scripts/
db_roles.py` applies both (the `migrate` container runs it after the migrations).
"""

from __future__ import annotations

import re

from sqlalchemy import Connection, text

API_ROLE = "codetutor_api"
DEMO_ROLE = "codetutor_demo"  # Deploy Step 2c: the public demo of a simulated class
ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
# Only long letters-and-digits passwords (`openssl rand -hex 24`): Postgres can't take a bound
# parameter in CREATE/ALTER ROLE, so the password is written into the statement, and this rule
# makes quoting a non-issue.
PASSWORD = re.compile(r"[A-Za-z0-9]{16,}")

# Whole-table privileges. Every table the API may touch is listed; anything else stays closed.
TABLE_GRANTS: dict[str, tuple[str, ...]] = {
    "problems": ("SELECT",),  # the student view only
    "test_results": ("SELECT",),
    # UPDATE only because `SELECT ... FOR UPDATE` (the per-user lock) requires it.
    "users": ("SELECT", "INSERT", "UPDATE"),
    "submissions": ("SELECT", "INSERT"),
    "sessions": ("SELECT", "INSERT", "DELETE"),
    "integrity_flags": ("SELECT",),  # the instructor routes
}
# hints: the API reads only what a student may see (api/hints.py HINT_COLUMNS) plus the columns
# it filters on, writes new requests, and changes only the rating.
HINT_SELECT_COLUMNS = (
    "id",
    "user_id",
    "problem_id",
    "problem_version",
    "submission_id",
    "level",
    "question",
    "created_at",
    "job_status",
    "text",
    "source",
    "rating",
)
HINT_UPDATE_COLUMNS = ("rating", "rated_at")


def _create_role(connection: Connection, role: str, password: str) -> None:
    """Create or update a login role and take every privilege away (grants come after)."""
    if not ROLE_NAME.fullmatch(role):
        raise ValueError(f"bad role name {role!r}: lower-case letters, digits and _ only")
    if not PASSWORD.fullmatch(password):
        raise ValueError("a role's password must be 16+ letters and digits (openssl rand -hex 24)")
    exists = connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role})
    verb = "ALTER" if exists else "CREATE"
    connection.execute(text(f"{verb} ROLE {role} WITH LOGIN PASSWORD '{password}'"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}"))
    connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}"))
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {role}"))


def apply_api_role(connection: Connection, role: str, password: str) -> None:
    """Create or update `role` and give it exactly the grants above. Safe to run again.

    Everything is revoked first, so a grant removed from this file is really taken away.
    """
    _create_role(connection, role, password)
    for table, privileges in TABLE_GRANTS.items():
        connection.execute(text(f"GRANT {', '.join(privileges)} ON {table} TO {role}"))
    connection.execute(text(f"GRANT SELECT ({', '.join(HINT_SELECT_COLUMNS)}) ON hints TO {role}"))
    connection.execute(text(f"GRANT INSERT ON hints TO {role}"))
    connection.execute(text(f"GRANT UPDATE ({', '.join(HINT_UPDATE_COLUMNS)}) ON hints TO {role}"))


# The demo API (api/demo.py) reads a simulated class through the teacher routes: names, the
# problems, who submitted what and when with which grade, and the integrity flags. Never code,
# output or editor summaries: the database enforces "no code on a public page".
DEMO_TABLE_GRANTS = {"users": "(id, name)", "problems": "", "integrity_flags": ""}
DEMO_SUBMISSION_COLUMNS = ("id", "user_id", "problem_id", "created_at", "result_status")


def apply_demo_role(connection: Connection, role: str, password: str) -> None:
    """Create or update the read-only role of the public demo. Safe to run again."""
    _create_role(connection, role, password)
    for table, columns in DEMO_TABLE_GRANTS.items():
        connection.execute(text(f"GRANT SELECT {columns} ON {table} TO {role}"))
    columns = ", ".join(DEMO_SUBMISSION_COLUMNS)
    connection.execute(text(f"GRANT SELECT ({columns}) ON submissions TO {role}"))
