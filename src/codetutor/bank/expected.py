"""Fill in the expected values of a problem's tests by running its reference solution.

Expected values are never typed by hand. The solution runs through the same sandbox as grading
(`execute()`), because the reference solution is code too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from codetutor.grader import Limits, execute
from codetutor.problems import Problem, TestCase, load_problem


class ExpectedError(Exception):
    """The reference solution could not produce expected values, or tests.yaml is inconsistent."""


def compute_expected(problem: Problem) -> dict[str, Any]:
    """Run solution.py on every test input and return {test_id: return value}."""
    limits = Limits(per_test_timeout_s=problem.time_limit_s)
    execution = execute(problem, problem.solution_code, limits)
    report = execution.report
    if report is None:
        raw = execution.raw
        reason = "timed out" if raw.timed_out else (raw.stderr.strip() or "crashed")
        raise ExpectedError(f"{problem.id}: solution.py did not run: {reason}")
    if not report.load.ok:
        raise ExpectedError(f"{problem.id}: solution.py did not load: {report.load.error}")

    expected: dict[str, Any] = {}
    for test in report.tests:
        if test.outcome != "returned":
            raise ExpectedError(
                f"{problem.id}: solution.py failed on test {test.id}: {test.error} "
                "(fix the solution or the input)"
            )
        expected[test.id] = test.actual
    return expected


def _same_value(a: Any, b: Any) -> bool:
    """Equal including types: 1, 1.0 and True are all different here."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def check_expected(problem: Problem) -> list[str]:
    """Return one message per test whose stored expected value differs from the solution's."""
    computed = compute_expected(problem)
    problems = []
    for test in problem.tests:
        if not test.has_expected:
            problems.append(f"{test.id}: no expected value (run fill_expected.py)")
        elif not _same_value(test.expected, computed[test.id]):
            problems.append(
                f"{test.id}: stored {json.dumps(test.expected)} but solution.py returns "
                f"{json.dumps(computed[test.id])}"
            )
    return problems


# --- Writing tests.yaml ---


def _format_float(value: float) -> str:
    """repr() of a float, but always with a '.' before the exponent.

    PyYAML reads 1e+16 as the STRING '1e+16'; it needs 1.0e+16 to read a float. We found this by
    testing, and the read-back check in write_tests_yaml would catch anything similar.
    """
    text = repr(value)
    if "e" in text and "." not in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}.0e{exponent}"
    return text


def _flow(value: Any) -> str:
    """Write a JSON-like value as YAML "flow" text (it looks like JSON)."""
    if isinstance(value, float):
        return _format_float(value)
    if isinstance(value, list):
        return "[" + ", ".join(_flow(item) for item in value) + "]"
    if isinstance(value, dict):
        items = (f"{json.dumps(key, ensure_ascii=False)}: {_flow(v)}" for key, v in value.items())
        return "{" + ", ".join(items) + "}"
    # None -> null, bool -> true/false, int, and str in double quotes. JSON strings are valid YAML,
    # and quoting every string avoids YAML surprises like "no" becoming False.
    return json.dumps(value, ensure_ascii=False)


def _test_line(test: TestCase, expected: Any) -> str:
    """One test as a single line, fields always in the same order."""
    fields = [
        f"id: {_flow(test.id)}",
        f"input: {_flow(test.input)}",
        f"expected: {_flow(expected)}",
        f"hidden: {_flow(test.hidden)}",
        f"compare: {_flow(str(test.compare))}",
    ]
    if test.note is not None:
        fields.append(f"note: {_flow(test.note)}")
    return "  - {" + ", ".join(fields) + "}"


def write_tests_yaml(folder: Path, problem: Problem, expected: dict[str, Any]) -> None:
    """Rewrite folder/tests.yaml with the given expected values.

    The new text is read back and checked BEFORE the file is written, so a failed check never
    leaves a broken tests.yaml behind. The file is fully regenerated, so '#' comments would be
    lost: explanations go in `note`.
    """
    lines = ["tests:"] + [_test_line(test, expected[test.id]) for test in problem.tests]
    text = "\n".join(lines) + "\n"
    path = Path(folder) / "tests.yaml"

    # Safety check: what YAML reads back must be exactly what we meant to write.
    written = yaml.safe_load(text)["tests"]
    for test, entry in zip(problem.tests, written, strict=True):
        if entry["id"] != test.id or not _same_value(entry["expected"], expected[test.id]):
            raise ExpectedError(f"{path}: test {test.id} did not survive the YAML round trip")
        if not _same_value(entry["input"], test.input):
            raise ExpectedError(f"{path}: input of {test.id} did not survive the YAML round trip")

    path.write_text(text, encoding="utf-8")


def fill_expected(folder: Path) -> tuple[Problem, int]:
    """Fill the expected values of the problem in `folder`. Returns (problem, number changed)."""
    problem = load_problem(folder, require_expected=False)
    expected = compute_expected(problem)
    changed = sum(
        1
        for test in problem.tests
        if not test.has_expected or not _same_value(test.expected, expected[test.id])
    )
    write_tests_yaml(folder, problem, expected)
    return load_problem(folder), changed
