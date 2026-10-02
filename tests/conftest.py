"""Shared test helpers: a valid problem as plain data, a way to write it to disk, and a
test database (Week 3)."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.db.models import Base
from codetutor.settings import database_url_for_tests

REPO_ROOT = Path(__file__).resolve().parents[1]

STARTER = '''def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    pass
'''

SOLUTION = '''def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    return sum(range(2, n + 1, 2))
'''

BUGGY = """def sum_of_evens(n: int) -> int:
    return sum(range(2, n, 2))
"""

# Test fixture data (not part of the problem bank), so writing expected values here is fine.
_TESTS: list[dict[str, Any]] = [
    {"id": "t01", "input": [10], "expected": 30, "hidden": False, "compare": "exact"},
    {"id": "t02", "input": [7], "expected": 12, "hidden": False, "compare": "exact"},
    {"id": "t03", "input": [2], "expected": 2, "hidden": False, "compare": "exact"},
    {"id": "t04", "input": [1], "expected": 0, "hidden": False, "compare": "exact"},
    {"id": "t05", "input": [0], "expected": 0, "hidden": True, "compare": "exact"},
    {"id": "t06", "input": [-5], "expected": 0, "hidden": True, "compare": "exact"},
    {"id": "t07", "input": [100], "expected": 2550, "hidden": True, "compare": "exact"},
    {"id": "t08", "input": [11], "expected": 30, "hidden": True, "compare": "exact"},
]

_META: dict[str, Any] = {
    "id": "cs1.loops.sum_of_evens",
    "version": 1,
    "title": "Sum of Even Numbers",
    "module": 3,
    "module_name": "Loops",
    "order": 1,
    "difficulty": "easy",
    "concepts": ["for_loops", "arithmetic"],
    "function_name": "sum_of_evens",
    "description_en": "Return the sum of the even numbers from 1 to n.",
    "description_ar": None,
    "hints": ["Hint one.", "Hint two.", "Hint three."],
    "author": "claude",
}


def valid_meta() -> dict[str, Any]:
    """A fresh copy of valid problem.yaml content."""
    return copy.deepcopy(_META)


def valid_tests() -> list[dict[str, Any]]:
    """A fresh copy of valid tests.yaml test entries."""
    return copy.deepcopy(_TESTS)


def valid_problem_data() -> dict[str, Any]:
    """Everything `Problem.model_validate` needs, as plain data."""
    return {
        **valid_meta(),
        "tests": valid_tests(),
        "starter_code": STARTER,
        "solution_code": SOLUTION,
        "buggy": {"off_by_one": BUGGY},
    }


ProblemWriter = Callable[..., Path]


@pytest.fixture
def write_problem(tmp_path: Path) -> ProblemWriter:
    """Return a function that writes a problem folder under tmp_path/problems and returns its path.

    Keyword arguments replace parts of the valid problem:
      meta, tests, starter, solution, buggy ({name: code}), folder ("cs1/03_loops/sum_of_evens"),
      skip (file names not to write).
    """

    def _write(
        *,
        meta: dict[str, Any] | None = None,
        tests: list[dict[str, Any]] | None = None,
        starter: str = STARTER,
        solution: str = SOLUTION,
        buggy: dict[str, str] | None = None,
        folder: str = "cs1/03_loops/sum_of_evens",
        skip: tuple[str, ...] = (),
    ) -> Path:
        path = tmp_path / "problems" / folder
        path.mkdir(parents=True)
        files = {
            "problem.yaml": yaml.safe_dump(valid_meta() if meta is None else meta, sort_keys=False),
            "tests.yaml": yaml.safe_dump({"tests": valid_tests() if tests is None else tests}),
            "starter.py": starter,
            "solution.py": solution,
        }
        for name, content in files.items():
            if name not in skip:
                (path / name).write_text(content, encoding="utf-8")
        buggy_files = {"off_by_one": BUGGY} if buggy is None else buggy
        if buggy_files:
            (path / "buggy").mkdir()
            for name, code in buggy_files.items():
                (path / "buggy" / f"{name}.py").write_text(code, encoding="utf-8")
        return path

    return _write


# --- Test database (Week 3) ---


def recreate_database(url: str) -> None:
    """Drop the database named in `url` (if it exists) and create it again, empty.

    Refuses names without "test", so a wrong URL can never wipe a real database.
    """
    name = conninfo_to_dict(url)["dbname"]
    if "test" not in name:
        raise RuntimeError(f"refusing to drop database {name!r}: test databases contain 'test'")
    # DROP/CREATE DATABASE can't run inside a transaction or while connected to that database,
    # so connect to the server's default "postgres" database with autocommit.
    admin = make_conninfo(url, dbname="postgres", connect_timeout=3)
    try:
        with psycopg.connect(admin, autocommit=True) as conn:
            # WITH (FORCE) also closes connections left open by an earlier, crashed run.
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except psycopg.OperationalError as exc:
        info = conninfo_to_dict(url)  # host and port only: the URL may contain a password
        where = f"{info.get('host')}:{info.get('port', 5432)}"
        pytest.fail(f"cannot reach Postgres at {where} ({exc}). Run `make db-up`.")


def alembic_config(url: str) -> Config:
    """The project's alembic.ini, pointed at `url` (env.py reads the "url" attribute)."""
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.attributes["url"] = url
    return config


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    """An engine on a fresh test database, built by the real migrations (not create_all)."""
    url = database_url_for_tests()
    recreate_database(url)
    command.upgrade(alembic_config(url), "head")
    engine = make_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    """A session on the test database. Every table is emptied after the test."""
    with Session(db_engine) as session:
        yield session
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
