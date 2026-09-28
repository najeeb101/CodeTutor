"""Compare a submission's actual output with the expected output.

Values are JSON-like: None, bool, int, float, str, list, dict (tuples are treated as lists).
Comparison is stricter than Python's `==` on purpose:
- `True == 1` in Python, but a function that should return a count must not pass by returning True.
- `30.0 == 30` in Python, but in "exact" mode an int answer must be an int. Problems whose answer
  is a float use "float" mode.
"""

from __future__ import annotations

import math
from typing import Any

from codetutor.problems.schema import CompareMode

FLOAT_REL_TOL = 1e-6
FLOAT_ABS_TOL = 1e-9


def _normalize(value: Any) -> Any:
    """Turn tuples into lists, recursively."""
    if isinstance(value, tuple | list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def _kind(value: Any) -> str:
    """A category name for a value. bool is checked before int because bool is a subclass of int."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    return "other"


def _exact_equal(actual: Any, expected: Any) -> bool:
    """Equality that also requires the same kind at every level (so True != 1 and 30.0 != 30)."""
    kind = _kind(actual)
    if kind != _kind(expected):
        return False
    if kind == "list":
        return len(actual) == len(expected) and all(
            _exact_equal(a, e) for a, e in zip(actual, expected, strict=True)
        )
    if kind == "dict":
        return actual.keys() == expected.keys() and all(
            _exact_equal(actual[key], expected[key]) for key in expected
        )
    return actual == expected


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _float_equal(actual: Any, expected: Any) -> bool:
    """Like exact, but numbers only need to be close (math.isclose), at any depth."""
    if _is_number(actual) and _is_number(expected):
        return math.isclose(actual, expected, rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL)
    kind = _kind(actual)
    if kind != _kind(expected):
        return False
    if kind == "list":
        return len(actual) == len(expected) and all(
            _float_equal(a, e) for a, e in zip(actual, expected, strict=True)
        )
    if kind == "dict":
        return actual.keys() == expected.keys() and all(
            _float_equal(actual[key], expected[key]) for key in expected
        )
    return _exact_equal(actual, expected)


def _unordered_equal(actual: Any, expected: Any) -> bool:
    """True if both are lists with the same items and the same counts, in any order.

    Items are compared with the exact rules (so True and 1 are different items).
    Must work when items can't be sorted, e.g. lists of lists or mixed types like [1, "a", None].
    """
    if not isinstance(actual, list) or not isinstance(expected, list):
        return False
    if len(actual) != len(expected):
        return False

    # We can't sort (items may be lists, dicts or mixed types), so we match items one by one:
    # every expected item must "use up" one equal item from what's left of the actual list.
    remaining = list(actual)  # a copy, so we don't change the caller's list
    for wanted in expected:
        for index, candidate in enumerate(remaining):
            if _exact_equal(candidate, wanted):
                del remaining[index]  # used up: it can't match a second expected item
                break
        else:
            return False  # no match found for this expected item
    return True  # same length and every expected item matched, so nothing is left over


def outputs_match(actual: Any, expected: Any, mode: CompareMode) -> bool:
    """Return True if `actual` counts as correct for `expected` under the given compare mode."""
    actual = _normalize(actual)
    expected = _normalize(expected)
    if mode == CompareMode.EXACT:
        return _exact_equal(actual, expected)
    if mode == CompareMode.FLOAT:
        return _float_equal(actual, expected)
    if mode == CompareMode.UNORDERED:
        return _unordered_equal(actual, expected)
    raise ValueError(f"unknown compare mode: {mode!r}")
