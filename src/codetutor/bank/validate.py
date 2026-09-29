"""Check that every problem is good enough to grade students and models with.

A problem is valid only if its reference solution passes everything, its starter code does not,
and every buggy solution is caught by at least one test (a simple form of mutation testing).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from codetutor.bank.expected import ExpectedError, check_expected
from codetutor.grader import GradeResult, GradeStatus, TestStatus, grade_many
from codetutor.problems import Problem, ProblemError, find_problem_folders, load_problem

# The reference solution must finish each test in less than this share of the time limit,
# so a reasonable student solution doesn't time out by accident.
MAX_SOLUTION_TIME_SHARE = 0.25


@dataclass
class ProblemReport:
    """The result of validating one problem."""

    name: str  # problem id, or the folder if the problem didn't load
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    visible: int = 0
    hidden: int = 0
    buggy_total: int = 0
    buggy_caught: int = 0
    hidden_only_bugs: list[str] = field(default_factory=list)  # bugs only hidden tests catch

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass
class BankReport:
    """The result of validating the whole problem bank."""

    problems: list[ProblemReport]
    warnings: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return all(report.valid for report in self.problems)


def _first_failure(result: GradeResult) -> str:
    """A short description of why a submission didn't get full marks."""
    if result.compile_error:
        return f"compile_error: {result.compile_error}"
    if result.error:
        return f"{result.status}: {result.error}"
    failing = next((test for test in result.tests if test.status != TestStatus.PASSED), None)
    if failing is None:
        return f"{result.status} with reward {result.reward}"
    detail = failing.error or f"expected {failing.expected!r}, got {failing.actual!r}"
    return f"{failing.test_id} {failing.status}: {detail}"


def _only_hidden_tests_fail(result: GradeResult) -> bool:
    """True if every visible test passed but some hidden test failed."""
    if not result.tests:
        return False
    visible_ok = all(t.status == TestStatus.PASSED for t in result.tests if not t.hidden)
    hidden_failed = any(t.status != TestStatus.PASSED for t in result.tests if t.hidden)
    return visible_ok and hidden_failed


def _check_solution(problem: Problem, result: GradeResult, report: ProblemReport) -> None:
    if result.reward != 1.0:
        report.errors.append(f"solution.py does not pass all tests ({_first_failure(result)})")
        return
    budget_ms = problem.time_limit_s * 1000 * MAX_SOLUTION_TIME_SHARE
    for test in result.tests:
        if test.duration_ms > budget_ms:
            report.errors.append(
                f"solution.py is too slow on {test.test_id}: {test.duration_ms:.0f} ms "
                f"(must be under {budget_ms:.0f} ms, 25% of the time limit)"
            )


def _check_starter(result: GradeResult, report: ProblemReport) -> None:
    if result.status in {GradeStatus.COMPILE_ERROR, GradeStatus.CRASHED}:
        report.errors.append(f"starter.py does not run ({_first_failure(result)})")
    elif result.reward == 1.0:
        report.errors.append("starter.py passes all tests (it should just `pass`)")


def _check_buggy(name: str, result: GradeResult, report: ProblemReport) -> None:
    if result.reward == 1.0:
        report.errors.append(
            f"buggy/{name}.py passed all tests → add a test that catches this mistake"
        )
        return
    report.buggy_caught += 1
    if result.status == GradeStatus.COMPILE_ERROR:
        report.warnings.append(
            f"buggy/{name}.py doesn't even load ({result.compile_error}); "
            "is that a realistic student mistake?"
        )
    if _only_hidden_tests_fail(result):
        report.hidden_only_bugs.append(name)


def validate_problem(problem: Problem) -> ProblemReport:
    """Run every check that needs code execution on one (already loaded) problem."""
    report = ProblemReport(
        name=problem.id,
        visible=len(problem.visible_tests),
        hidden=len(problem.hidden_tests),
        buggy_total=len(problem.buggy),
    )
    if not problem.buggy:
        report.errors.append("no buggy solutions (add 1-3 files to buggy/)")

    try:
        mismatches = check_expected(problem)
    except ExpectedError as exc:
        report.errors.append(str(exc))
        return report
    report.errors.extend(f"tests.yaml {message}" for message in mismatches)

    # Grade solution, starter and all buggy solutions in parallel, with the problem's own limits.
    buggy_names = sorted(problem.buggy)
    jobs = [(problem, problem.solution_code), (problem, problem.starter_code)]
    jobs += [(problem, problem.buggy[name]) for name in buggy_names]
    solution, starter, *buggy_results = grade_many(jobs, reveal_hidden=True)

    _check_solution(problem, solution, report)
    _check_starter(starter, report)
    for name, result in zip(buggy_names, buggy_results, strict=True):
        _check_buggy(name, result, report)
    return report


def validate_bank(root: Path | None = None) -> BankReport:
    """Validate every problem under `root` (default: the repo's problems/ folder)."""
    reports: list[ProblemReport] = []
    ids: Counter[str] = Counter()
    for folder in find_problem_folders(root):
        try:
            problem = load_problem(folder)
        except ProblemError as exc:
            reports.append(ProblemReport(name=str(folder), errors=[str(exc)]))
            continue
        ids[problem.id] += 1
        reports.append(validate_problem(problem))

    # Can't happen today (the id must match the folder, and folders are unique), but it is a cheap
    # safety net in case that loader rule ever changes.
    for report in reports:
        if ids[report.name] > 1:
            report.errors.append(f"id {report.name!r} is used by {ids[report.name]} problems")

    bank = BankReport(problems=reports)
    loaded = [r for r in reports if r.buggy_total]
    with_hidden_only = sum(1 for r in loaded if r.hidden_only_bugs)
    if loaded and with_hidden_only < len(loaded) / 2:
        bank.warnings.append(
            f"only {with_hidden_only}/{len(loaded)} problems have a bug that only hidden tests "
            "catch; aim for at least half"
        )
    return bank


def format_report(bank: BankReport) -> str:
    """The human-readable report printed by scripts/validate_problems.py."""
    width = max((len(report.name) for report in bank.problems), default=0) + 2
    lines = []
    for report in bank.problems:
        if report.valid:
            summary = (
                f"({report.visible + report.hidden} tests: {report.visible} visible, "
                f"{report.hidden} hidden; {report.buggy_caught}/{report.buggy_total} buggy caught"
            )
            if report.hidden_only_bugs:
                summary += f"; hidden-only: {', '.join(report.hidden_only_bugs)}"
            lines.append(f"{report.name:<{width}}✅ valid   {summary})")
        else:
            lines.append(f"{report.name:<{width}}❌ invalid")
            lines.extend(f"    ✗ {error}" for error in report.errors)
        lines.extend(f"    ⚠ {warning}" for warning in report.warnings)
    lines.extend(f"⚠ {warning}" for warning in bank.warnings)
    valid = sum(1 for report in bank.problems if report.valid)
    invalid = len(bank.problems) - valid
    lines.append(f"Summary: {valid} valid, {invalid} invalid")
    return "\n".join(lines)
