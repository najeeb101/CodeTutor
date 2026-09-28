"""Tests for output comparison. Subtle equality bugs here would let wrong answers earn reward."""

from __future__ import annotations

from typing import Any

import pytest

from codetutor.grader.compare import outputs_match
from codetutor.problems.schema import CompareMode

EXACT = CompareMode.EXACT
FLOAT = CompareMode.FLOAT
UNORDERED = CompareMode.UNORDERED


# --- exact ---


@pytest.mark.parametrize(
    "actual, expected",
    [
        (30, 30),
        ("abc", "abc"),
        (None, None),
        (True, True),
        ([1, [2, 3]], [1, [2, 3]]),
        ((1, 2), [1, 2]),  # tuples are normalized to lists
        ([(1, 2), (3, 4)], [[1, 2], [3, 4]]),  # also nested
        ({"a": 1, "b": [1, 2]}, {"b": [1, 2], "a": 1}),  # dict key order doesn't matter
    ],
)
def test_exact_matches(actual: Any, expected: Any) -> None:
    assert outputs_match(actual, expected, EXACT)


@pytest.mark.parametrize(
    "actual, expected",
    [
        (True, 1),  # Python says True == 1; we don't
        (False, 0),
        (1, True),
        ([True], [1]),  # also inside lists
        (30.0, 30),  # int answer returned as float
        (30, 30.0),
        (None, 0),
        ("1", 1),
        ([1, 2], [2, 1]),  # order matters in exact mode
        ([1, 2], [1, 2, 3]),
        ({"a": 1}, {"a": 1, "b": 2}),
        ({"a": True}, {"a": 1}),
        ([[1, 2]], [[1, 2, 3]]),
    ],
)
def test_exact_mismatches(actual: Any, expected: Any) -> None:
    assert not outputs_match(actual, expected, EXACT)


# --- float ---


@pytest.mark.parametrize(
    "actual, expected",
    [
        (0.1 + 0.2, 0.3),
        (98.60000000000001, 98.6),
        (32, 32.0),  # int is fine in float mode
        ([1.0000000001, 2.0], [1.0, 2.0]),
        ([[0.1 + 0.2]], [[0.3]]),
        ({"x": 0.1 + 0.2}, {"x": 0.3}),
        (0.0, 1e-10),  # abs_tol near zero
        (["a", 1.5], ["a", 1.5]),
    ],
)
def test_float_matches(actual: Any, expected: Any) -> None:
    assert outputs_match(actual, expected, FLOAT)


@pytest.mark.parametrize(
    "actual, expected",
    [
        (1.0, 1.1),
        (True, 1.0),  # bools are not numbers here
        (1.0, True),
        ([1.0, 2.0], [1.0]),
        ([1.0, 2.0], [2.0, 1.0]),
        ("1.0", 1.0),
        (None, 0.0),
    ],
)
def test_float_mismatches(actual: Any, expected: Any) -> None:
    assert not outputs_match(actual, expected, FLOAT)


# --- unordered: TODO(najeeb). These fail until _unordered_equal is implemented. ---


@pytest.mark.parametrize(
    "actual, expected",
    [
        ([3, 1, 2], [1, 2, 3]),
        ([], []),
        ([1, 1, 2], [1, 2, 1]),  # duplicates, same counts
        ([[3, 4], [1, 2]], [[1, 2], [3, 4]]),  # items that are lists
        ([None, "a", 1], [1, None, "a"]),  # mixed types, can't be sorted
        ([{"a": 1}, {"b": 2}], [{"b": 2}, {"a": 1}]),  # dicts can't be sorted either
        (((1, 2), (3,)), [[3], [1, 2]]),  # tuples normalized first
    ],
)
def test_unordered_matches(actual: Any, expected: Any) -> None:
    assert outputs_match(actual, expected, UNORDERED)


@pytest.mark.parametrize(
    "actual, expected",
    [
        ([1, 2], [1, 2, 3]),  # missing item
        ([1, 2, 3], [1, 2]),  # extra item
        ([1, 1, 2], [1, 2, 2]),  # same items, different counts
        ([True, 2], [1, 2]),  # True is not 1
        ([[2, 1]], [[1, 2]]),  # only the top level is unordered
        (5, [5]),  # not a list
        ([5], 5),
        (None, []),
    ],
)
def test_unordered_mismatches(actual: Any, expected: Any) -> None:
    assert not outputs_match(actual, expected, UNORDERED)
