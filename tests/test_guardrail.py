"""The hint guardrail (Week 4 Step 0): its rules, the bank's own hints, and labelled leaks.

docs/tutor.md §1 reports the numbers these tests measure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from codetutor.problems import Problem
from codetutor.problems.loader import load_all
from codetutor.tutor.guardrail import MAX_DETAIL_CHARS, Violation, check_hint, solution_lines

CASES_FILE = Path(__file__).parent / "hints" / "guardrail_cases.yaml"
FIZZ = "cs1.loops.fizzbuzz"

# Hint 3 is the "bottom-out" hint (shown only when a student asks for the last hint). In these
# problems it contains lines of solution.py (measured 2026-10-03). Pinned, so a change to the
# rules or the hints shows up here.
BOTTOM_OUT_LEAKS = {
    "cs1.loops.count_digits": ["n //= 10"],
    "cs1.functions.gcd": ["a, b = b, a % b"],
    "cs1.dicts.word_frequency": ["counts[word] = counts.get(word, 0) + 1"],
    "cs1.dicts.first_unique_char": ["counts[char] = counts.get(char, 0) + 1"],
    "cs1.dicts.group_anagrams": ['key = "".join(sorted(word))'],
    "cs1.dicts.two_sum": ["return [seen[need], j]"],
    "cs1.recursion.recursive_sum": ["return nums[0] + recursive_sum(nums[1:])"],
    "cs1.recursion.fibonacci": ["previous, current = current, previous + current"],
    "cs1.recursion.binary_search": [
        "high = len(nums) - 1",
        "high = middle - 1",
        "low = middle + 1",
        "middle = (low + high) // 2",
    ],
}


@pytest.fixture(scope="module")
def bank() -> dict[str, Problem]:
    return {problem.id: problem for problem in load_all()}


@pytest.fixture(scope="module")
def fizz(bank: dict[str, Problem]) -> Problem:
    return bank[FIZZ]


def _kinds(violations: list[Violation]) -> set[str]:
    return {violation.kind for violation in violations}


def _with_solution(problem: Problem, body: str) -> Problem:
    """`problem` with a solution made of the starter's def line plus `body`."""
    def_line = problem.starter_code.splitlines()[0]
    code = f"{def_line}\n    {body}\n"
    return problem.model_copy(update={"solution_code": code})


# --- solution_lines --------------------------------------------------------------------------


def test_solution_lines_leave_out_starter_lines_comments_and_trivial_lines(
    fizz: Problem, bank: dict[str, Problem]
) -> None:
    assert solution_lines(fizz) == [
        "elif number % 3 == 0:",
        "elif number % 5 == 0:",
        "for number in range(1, n + 1):",
        "if number % 15 == 0:",
        'result.append("Buzz")',
        'result.append("Fizz")',
        'result.append("FizzBuzz")',
        "result.append(str(number))",
    ]
    # The solution has `for word in text.split():  # no argument: ...` and `counts = {}`.
    words = solution_lines(bank["cs1.dicts.word_frequency"])
    assert "for word in text.split():" in words
    assert "counts = {}" not in words


def test_a_hash_inside_a_string_is_not_a_comment(fizz: Problem) -> None:
    problem = _with_solution(fizz, 'return "#" + str(n)  # a real comment')
    assert solution_lines(problem) == ['return "#" + str(n)']


@pytest.mark.parametrize(
    "line",
    ["count = 0", "i += 1", "result = []", "return result", "return -1", 'return "A"', "else:"]
    + ["for word in words:", "if need in seen:"],
)
def test_trivial_lines_are_not_secrets(fizz: Problem, line: str) -> None:
    body = line if not line.endswith(":") else f"{line}\n        pass"
    assert solution_lines(_with_solution(fizz, body)) == []


@pytest.mark.parametrize(
    "line", ["n //= 10", "a, b = b, a % b", "if n < 2:", "total += nums[0]", "while b != 0:"]
)
def test_short_lines_with_real_content_are_secrets(fizz: Problem, line: str) -> None:
    body = line if not line.endswith(":") else f"{line}\n        pass"
    assert solution_lines(_with_solution(fizz, body)) == [line]


def test_every_bank_problem_has_secret_lines(bank: dict[str, Problem]) -> None:
    assert [pid for pid, problem in bank.items() if not solution_lines(problem)] == []


# --- the rules -------------------------------------------------------------------------------


def test_spacing_and_quote_style_do_not_hide_a_solution_line(fizz: Problem) -> None:
    for hint in ["call result.append('Fizz') here", 'call result.append(  "Fizz" ) here']:
        assert check_hint(hint, fizz) == [Violation("solution_line", 'result.append("Fizz")')]


def test_text_the_student_already_has_is_allowed(fizz: Problem) -> None:
    hint = "Your `result.append(str(number))` is fine; look at `if number % 15 == 0:` again."
    assert _kinds(check_hint(hint, fizz)) == {"solution_line", "code_statement"}
    student = "    if number % 15 == 0:\n        result.append(str(number))\n"
    assert check_hint(hint, fizz, student_code=student) == []


def test_starter_and_description_text_is_allowed(fizz: Problem) -> None:
    def_line = fizz.starter_code.splitlines()[0]
    assert def_line.startswith("def fizzbuzz")
    assert check_hint(f"Keep the first line as it is:\n{def_line}", fizz) == []


def test_expressions_are_allowed_but_statements_are_not(fizz: Problem) -> None:
    assert check_hint("The test `number % 7 == 0` is true for 14.", fizz) == []
    assert check_hint("Use `total = total + 1` there.", fizz) == [
        Violation("code_statement", "total = total + 1")
    ]


def test_one_code_line_is_a_statement_and_two_are_a_block(fizz: Problem) -> None:
    assert _kinds(check_hint("Do this:\ntotal = 0", fizz)) == {"code_statement"}
    two = check_hint("Do this:\nfor i in range(3):\n    print(i)", fizz)
    assert two == [Violation("code_block", "for i in range(3):\n    print(i)")]


def test_a_lone_expression_line_is_prose(fizz: Problem) -> None:
    assert check_hint("Yes\nfizzbuzz(7)\nExample: fizzbuzz(15)", fizz) == []


def test_fences_are_code_unless_they_only_quote_allowed_text(fizz: Problem) -> None:
    student = "for k in range(n):\n    print(k)\n"
    quoted = f"Your loop:\n```python\n{student}```\nWhat does it print for n = 0?"
    assert check_hint(quoted, fizz, student_code=student) == []
    other = "Like this:\n```\nx = 1\n```"
    assert check_hint(other, fizz) == [Violation("code_block", "x = 1")]
    unclosed = "Like this:\n~~~\nwhile True:\n    pass"
    assert _kinds(check_hint(unclosed, fizz)) == {"code_block"}


def test_the_detail_is_cut(fizz: Problem) -> None:
    long_line = "x = " + "1 + " * 200 + "1"
    [violation] = check_hint(f"`{long_line}`", fizz)
    assert len(violation.detail) == MAX_DETAIL_CHARS + 1 and violation.detail.endswith("…")


# --- the bank's own hints --------------------------------------------------------------------


def test_no_false_alarm_on_the_banks_hints_1_and_2(bank: dict[str, Problem]) -> None:
    checked = {
        (pid, number): check_hint(problem.hints[number - 1], problem)
        for pid, problem in bank.items()
        for number in (1, 2)
    }
    assert len(checked) == 66
    assert {key: value for key, value in checked.items() if value} == {}


def test_bottom_out_hints_with_solution_lines_are_pinned(bank: dict[str, Problem]) -> None:
    flagged = {}
    for pid, problem in bank.items():
        violations = check_hint(problem.hints[2], problem)
        if violations:
            assert _kinds(violations) == {"solution_line"}, pid
            flagged[pid] = sorted(violation.detail for violation in violations)
    assert flagged == BOTTOM_OUT_LEAKS


# --- generated leaks: every problem, every solution line -------------------------------------


def _generated_leaks(problem: Problem) -> list[str]:
    solution = problem.solution_code
    leaks = [f"Here is the answer:\n```python\n{solution}```", f"Try this:\n{solution}"]
    for line in solution_lines(problem):
        leaks.append(f"At that point you could write {line} and move on.")
        leaks.append(f"Use `{line}` there.")
    return leaks


def test_every_generated_leak_is_caught(bank: dict[str, Problem]) -> None:
    missed = []
    total = 0
    for problem in bank.values():
        for leak in _generated_leaks(problem):
            total += 1
            if not check_hint(leak, problem):
                missed.append((problem.id, leak))
    assert total == 2 * 33 + 2 * sum(len(solution_lines(p)) for p in bank.values())
    assert missed == []


# --- hand-written cases ----------------------------------------------------------------------


def _load_cases() -> list[dict[str, Any]]:
    cases = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))
    allowed = {"problem", "hint", "expect", "leak", "why", "kinds", "student_code"}
    for case in cases:
        assert set(case) <= allowed, case
        assert case["expect"] in ("ok", "blocked") and isinstance(case["leak"], bool), case
    return cases


CASES = _load_cases()


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{n:02d}-{c['problem'].split('.')[-1]}" for n, c in enumerate(CASES)]
)
def test_hand_written_case(bank: dict[str, Problem], case: dict[str, Any]) -> None:
    problem = bank[case["problem"]]
    violations = check_hint(case["hint"], problem, student_code=case.get("student_code", ""))
    verdict = "blocked" if violations else "ok"
    assert verdict == case["expect"], (case["why"], violations)
    assert set(case.get("kinds", [])) <= _kinds(violations), (case["why"], violations)


def test_the_cases_cover_good_hints_leaks_and_known_misses() -> None:
    def count(expect: str, leak: bool) -> int:
        return sum(1 for c in CASES if c["expect"] == expect and c["leak"] is leak)

    # good hints, caught leaks, accepted false alarms, known misses (docs/tutor.md §1)
    assert (count("ok", False), count("blocked", True)) == (10, 10)
    assert (count("blocked", False), count("ok", True)) == (1, 3)
