"""Shared test helpers: a valid problem as plain data, and a way to write it to disk."""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

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
