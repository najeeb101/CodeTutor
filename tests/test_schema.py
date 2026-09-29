"""Tests for the Problem / TestCase schema: every static rule rejects bad input."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from codetutor.problems import Problem, StudentProblem, TestCase
from conftest import valid_problem_data


def build(**changes: Any) -> Problem:
    data = valid_problem_data()
    data.update(changes)
    return Problem.model_validate(data)


def build_with_test_change(index: int, **changes: Any) -> Problem:
    data = valid_problem_data()
    data["tests"][index].update(changes)
    return Problem.model_validate(data)


def test_valid_problem_builds() -> None:
    problem = build()
    assert problem.id == "cs1.loops.sum_of_evens"
    assert len(problem.visible_tests) == 4
    assert len(problem.hidden_tests) == 4
    assert problem.time_limit_s == 2.0  # default
    assert problem.check_input_unchanged is False  # default: old problems are not affected


def test_problem_is_frozen() -> None:
    problem = build()
    with pytest.raises(ValidationError):
        problem.title = "changed"  # type: ignore[misc]


# --- problem.yaml fields ---


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        build(dificulty="easy")


@pytest.mark.parametrize(
    "bad_id", ["loops.sum_of_evens", "cs1.Loops.sum", "cs1.loops.sum-of-evens", ""]
)
def test_bad_problem_id(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="id"):
        build(id=bad_id)


@pytest.mark.parametrize("module", [0, 9])
def test_module_out_of_range(module: int) -> None:
    with pytest.raises(ValidationError, match="module"):
        build(module=module)


def test_unknown_concept_is_rejected() -> None:
    with pytest.raises(ValidationError, match="concepts"):
        build(concepts=["loops"])


def test_duplicate_concepts_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        build(concepts=["arithmetic", "arithmetic"])


def test_bad_difficulty() -> None:
    with pytest.raises(ValidationError, match="difficulty"):
        build(difficulty="impossible")


@pytest.mark.parametrize("hints", [["one", "two"], ["1", "2", "3", "4"]])
def test_hints_must_be_exactly_three(hints: list[str]) -> None:
    with pytest.raises(ValidationError, match="hints"):
        build(hints=hints)


@pytest.mark.parametrize(
    "code_hint",
    ["```python\nreturn n\n```", "Try this:\nfor i in range(n):\n    total += i"],
)
def test_hints_must_not_contain_code(code_hint: str) -> None:
    with pytest.raises(ValidationError, match="looks like code"):
        build(hints=["ok", "ok", code_hint])


def test_hint_mentioning_code_words_in_a_sentence_is_allowed() -> None:
    build(hints=["ok", "ok", "For each number in range(1, n + 1), check if it is even."])


def test_function_name_must_be_identifier() -> None:
    with pytest.raises(ValidationError, match="not a valid Python function name"):
        build(function_name="sum-of-evens")


def test_function_missing_from_starter() -> None:
    with pytest.raises(ValidationError, match="starter.py does not define"):
        build(starter_code="def something_else():\n    pass\n")


def test_function_missing_from_solution() -> None:
    with pytest.raises(ValidationError, match="solution.py does not define"):
        build(solution_code="sum_of_evens = lambda n: 0\n")


def test_syntax_error_in_solution_reports_line() -> None:
    with pytest.raises(ValidationError, match="solution.py has a syntax error on line 2"):
        build(solution_code="def sum_of_evens(n):\n    return (\n")


def test_time_limit_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="time_limit_s"):
        build(time_limit_s=0)


# --- tests.yaml rules ---


def test_missing_hidden_flag_is_rejected() -> None:
    data = valid_problem_data()
    del data["tests"][0]["hidden"]
    with pytest.raises(ValidationError, match="hidden"):
        Problem.model_validate(data)


def test_input_must_be_a_list() -> None:
    with pytest.raises(ValidationError, match="input"):
        build_with_test_change(0, input=10)


@pytest.mark.parametrize(
    "bad_value", [datetime.date(2026, 1, 1), float("nan"), float("inf"), (1, 2), {1: "a"}]
)
def test_input_must_be_json_compatible(bad_value: object) -> None:
    with pytest.raises(ValidationError):
        build_with_test_change(0, input=[bad_value])


def test_duplicate_test_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate test ids: t01"):
        build_with_test_change(1, id="t01")


def test_too_few_tests() -> None:
    data = valid_problem_data()
    data["tests"] = data["tests"][:7]
    with pytest.raises(ValidationError, match="at least 8 tests"):
        Problem.model_validate(data)


def test_too_few_hidden_tests() -> None:
    data = valid_problem_data()
    for test in data["tests"][4:6]:
        test["hidden"] = False
    with pytest.raises(ValidationError, match="at least 3 hidden tests"):
        Problem.model_validate(data)


def test_too_few_visible_tests() -> None:
    data = valid_problem_data()
    for test in data["tests"][:2]:
        test["hidden"] = True
    with pytest.raises(ValidationError, match="at least 3 visible tests"):
        Problem.model_validate(data)


def test_bad_compare_mode() -> None:
    with pytest.raises(ValidationError, match="compare"):
        build_with_test_change(0, compare="fuzzy")


def test_has_expected_distinguishes_missing_from_null() -> None:
    missing = TestCase(id="t01", input=[1], hidden=False, compare="exact")
    null = TestCase(id="t01", input=[1], expected=None, hidden=False, compare="exact")
    assert not missing.has_expected
    assert null.has_expected
    assert null.expected is None


# --- views ---


def test_student_view_hides_secrets() -> None:
    problem = build()
    view = problem.to_student_view()
    assert isinstance(view, StudentProblem)
    dumped = view.model_dump()
    for secret in ("solution_code", "buggy", "hints", "tests"):
        assert secret not in dumped
    assert [example.id for example in view.examples] == ["t01", "t02", "t03", "t04"]
    assert "sum(range(2, n + 1, 2))" not in view.model_dump_json()


def test_student_view_shows_the_input_rule() -> None:
    # It is a rule the student must follow, like the time limit, so they are allowed to see it.
    assert build(check_input_unchanged=True).to_student_view().check_input_unchanged is True


def test_internal_view_is_json_serializable() -> None:
    problem = build()
    text = problem.model_dump_json()
    assert Problem.model_validate_json(text) == problem
