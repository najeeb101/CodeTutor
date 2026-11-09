"""Create or update the API's database role and its grants (Deploy Step 2a, db/roles.py).

Usage:
    API_DB_PASSWORD=... python scripts/db_roles.py

Connects with DATABASE_URL (the owner). Safe to run again: the role's password is set and its
grants are rebuilt from scratch. The `migrate` container runs it after the migrations.
"""

from __future__ import annotations

import sys

from sqlalchemy.exc import OperationalError

from codetutor.db.engine import make_engine
from codetutor.db.roles import API_ROLE, apply_api_role
from codetutor.settings import API_DB_PASSWORD_ENV, api_db_password


def main() -> int:
    password = api_db_password()
    if password is None:
        print(f"❌ {API_DB_PASSWORD_ENV} is not set (the API role's password;", end=" ")
        print("make one with: openssl rand -hex 24)")
        return 1
    engine = make_engine()
    try:
        with engine.begin() as connection:
            apply_api_role(connection, API_ROLE, password)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except OperationalError as exc:
        print(f"❌ cannot reach Postgres ({exc.orig})")
        return 1
    finally:
        engine.dispose()
    print(f"✅ role {API_ROLE}: password set, grants rebuilt (db/roles.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
