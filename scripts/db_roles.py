"""Create or update a database role and its grants (Deploy Steps 2a and 2c, db/roles.py).

Usage:
    API_DB_PASSWORD=... python scripts/db_roles.py          # the API's role, on DATABASE_URL
    DEMO_DB_PASSWORD=... python scripts/db_roles.py --demo  # the read-only demo role, on
                                                            # DATABASE_URL (a simulation database)

Connects with DATABASE_URL (the owner). Safe to run again: the role's password is set and its
grants are rebuilt from scratch. The `migrate` and `demo-seed` containers run it.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import OperationalError

from codetutor.db.admin import database_name
from codetutor.db.engine import make_engine
from codetutor.db.roles import API_ROLE, DEMO_ROLE, apply_api_role, apply_demo_role
from codetutor.settings import (
    API_DB_PASSWORD_ENV,
    DEMO_DB_PASSWORD_ENV,
    api_db_password,
    database_url,
    demo_db_password,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true", help="the read-only demo role instead")
    args = parser.parse_args()
    role, env, password, apply = (
        (DEMO_ROLE, DEMO_DB_PASSWORD_ENV, demo_db_password(), apply_demo_role)
        if args.demo
        else (API_ROLE, API_DB_PASSWORD_ENV, api_db_password(), apply_api_role)
    )
    if password is None:
        print(f"❌ {env} is not set (the role's password; make one with: openssl rand -hex 24)")
        return 1
    if args.demo and "sim" not in database_name(database_url()):
        print("❌ the demo role is only for a simulation database (its name must contain 'sim')")
        return 1
    engine = make_engine()
    try:
        with engine.begin() as connection:
            apply(connection, role, password)
    except ValueError as exc:
        print(f"❌ {exc}")
        return 1
    except OperationalError as exc:
        print(f"❌ cannot reach Postgres ({exc.orig})")
        return 1
    finally:
        engine.dispose()
    print(f"✅ role {role}: password set, grants rebuilt (db/roles.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
