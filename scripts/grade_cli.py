"""Grade one Python file against one problem and print the result.

Usage:
    python scripts/grade_cli.py cs1.loops.sum_of_evens my_solution.py
    python scripts/grade_cli.py cs1.loops.sum_of_evens my_solution.py --reveal-hidden
    python scripts/grade_cli.py cs1.loops.sum_of_evens my_solution.py --json
    python scripts/grade_cli.py cs1.loops.sum_of_evens my_solution.py --sandbox docker
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codetutor.grader import (
    DockerSandbox,
    GradeResult,
    SandboxUnavailableError,
    SubprocessSandbox,
    TestResult,
    TestStatus,
    grade,
)
from codetutor.problems import ProblemError, get_problem

MAX_VALUE_WIDTH = 40


def _short(value: object) -> str:
    """A value as JSON, cut to MAX_VALUE_WIDTH characters."""
    text = json.dumps(value)
    return text if len(text) <= MAX_VALUE_WIDTH else text[: MAX_VALUE_WIDTH - 3] + "..."


def _details(test: TestResult) -> str:
    if test.status == TestStatus.PASSED:
        return ""
    if test.error:
        return test.error
    if test.revealed:
        expected, actual = _short(test.expected), _short(test.actual)
        return f"input {_short(test.input)}: expected {expected}, got {actual}"
    return "(hidden test)"


def format_result(result: GradeResult) -> str:
    """The human-readable output."""
    lines = [
        f"Problem: {result.problem_id} (version {result.problem_version})",
        f"Status:  {result.status}",
        f"Reward:  {result.reward}  ({result.passed}/{result.total} tests passed)",
    ]
    if result.compile_error:
        lines.append(f"Error:   {result.compile_error}")
    if result.error:
        lines.append(f"Error:   {result.error}")
    if result.tests:
        lines.append("")
        lines.append(f"      {'test':<6}{'kind':<9}{'result':<15}details")
        for test in result.tests:
            mark = "✅" if test.status == TestStatus.PASSED else "❌"
            kind = "hidden" if test.hidden else "visible"
            lines.append(f"  {mark}  {test.test_id:<6}{kind:<9}{test.status:<15}{_details(test)}")
    if result.stdout:
        lines.append("")
        lines.append("Your printed output:")
        lines.append(result.stdout.rstrip("\n"))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("problem_id", help="e.g. cs1.loops.sum_of_evens")
    parser.add_argument("file", type=Path, help="the Python file to grade")
    parser.add_argument("--reveal-hidden", action="store_true", help="show hidden test details")
    parser.add_argument("--json", action="store_true", help="print the raw GradeResult as JSON")
    parser.add_argument(
        "--sandbox",
        choices=["subprocess", "docker"],
        default="subprocess",
        help="where the code runs (docker: safer, ~1 s slower; needs Docker)",
    )
    args = parser.parse_args()

    try:
        problem = get_problem(args.problem_id)
    except ProblemError as exc:
        parser.error(str(exc))
    try:
        code = args.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        parser.error(f"cannot read {args.file}: {exc}")
    try:
        sandbox = DockerSandbox() if args.sandbox == "docker" else SubprocessSandbox()
    except SandboxUnavailableError as exc:
        parser.error(str(exc))
    result = grade(problem, code, reveal_hidden=args.reveal_hidden, sandbox=sandbox)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
