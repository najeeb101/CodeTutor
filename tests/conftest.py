"""Shared test helpers: a valid problem as plain data, a way to write it to disk, and a
test database (Week 3)."""

from __future__ import annotations

import copy
import hashlib
import math
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from codetutor.db import admin
from codetutor.db.engine import make_engine
from codetutor.db.models import EMBEDDING_DIMENSIONS, Base
from codetutor.evals.records import ModelReply
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
    """Drop and re-create the test database (names must contain "test"; db/admin.py)."""
    try:
        admin.recreate_database(url, must_contain="test")
    except admin.DatabaseUnreachableError as exc:
        pytest.fail(str(exc))


alembic_config = admin.alembic_config  # tests import it from here


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


class HashingEmbedder:
    """A fake embedder for tests (no Ollama): each word adds 1 at a position chosen by its hash.

    Texts that share words get similar vectors, always the same ones, so search tests are
    deterministic. `calls` records how many texts each embed_documents call got.
    """

    def __init__(self, name: str = "fake/hashing", dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.name = name
        self.dimensions = dimensions
        self.calls: list[int] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            position = int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % self.dimensions
            vector[position] += 1.0
        if not any(vector):
            vector[0] = 1.0  # pgvector's cosine distance of an all-zero vector is NaN
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector]


class ScriptedModel:
    """A fake chat model: answers from a list (text, a ModelReply, or an exception to raise)."""

    name = "fake/scripted"

    def __init__(self, *replies: str | ModelReply | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
    ) -> ModelReply:
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, ModelReply) else ModelReply(text=reply, prompt_tokens=900)


def docker_runtime() -> str | None:
    """The container runtime the docker tests should use: $TEST_SANDBOX_RUNTIME (CI sets `runsc`
    for the gVisor job), else None = Docker's default (runc)."""
    return os.environ.get("TEST_SANDBOX_RUNTIME") or None
