"""Public grading API. The ONE grading path used by students, model evals and the RL reward.

grade(problem, code) -> GradeResult
grade_many([(problem, code), ...]) -> [GradeResult, ...]
"""

from __future__ import annotations

import secrets
import signal
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pydantic import ValidationError

from codetutor.grader.compare import outputs_match
from codetutor.grader.models import (
    GradeResult,
    GradeStatus,
    Limits,
    RawResult,
    RunnerReport,
    SandboxJob,
    SandboxTest,
    TestReport,
    TestResult,
    TestStatus,
)
from codetutor.grader.sandbox import Sandbox, SubprocessSandbox
from codetutor.problems.schema import Problem, TestCase

TRUNCATION_NOTE = "\n[output truncated]"
# Safe to show for hidden tests too: it says nothing about the input.
INPUT_CHANGED_ERROR = "your function changed its input; build and return a new list instead"


class GraderError(Exception):
    """The grader was called incorrectly (not a problem with the submission)."""


@dataclass(frozen=True)
class Execution:
    """The result of running code in the sandbox, before any comparison.

    `report` is None if the runner didn't produce a valid report (crash, timeout, output flood).
    """

    raw: RawResult
    report: RunnerReport | None


def _resolve_limits(problem: Problem, limits: Limits | None) -> Limits:
    """Use the caller's limits if given; else defaults with the problem's per-test time limit."""
    if limits is not None:
        return limits
    return Limits(per_test_timeout_s=problem.time_limit_s)


def _parse_report(raw: RawResult, token: str, test_ids: list[str]) -> RunnerReport | None:
    """Find the report after the LAST token and validate it. Return None if it's missing or bad.

    The child's output is untrusted: student code can write to stdout too. It can't produce a
    valid report without the token, and even with the token it can only report return values,
    never "passed" (the parent compares).
    """
    position = raw.stdout.rfind(token)
    if position == -1:
        return None
    try:
        report = RunnerReport.model_validate_json(raw.stdout[position + len(token) :].strip())
    except ValidationError:
        return None
    if report.load.ok and [test.id for test in report.tests] != test_ids:
        return None
    return report


def execute(
    problem: Problem, code: str, limits: Limits, sandbox: Sandbox | None = None
) -> Execution:
    """Run `code` on every test input of `problem` in the sandbox. No comparison happens here.

    Used by grade() and by scripts/fill_expected.py (Step 3), so both share one execution path.
    """
    sandbox = SubprocessSandbox() if sandbox is None else sandbox
    token = secrets.token_hex(16)  # new random token for every run
    job = SandboxJob(
        token=token,
        code=code,
        function_name=problem.function_name,
        tests=[SandboxTest(id=test.id, input=test.input) for test in problem.tests],
        per_test_timeout_s=limits.per_test_timeout_s,
        total_timeout_s=limits.total_for(len(problem.tests)),
        memory_mb=limits.memory_mb,
        max_file_mb=limits.max_file_mb,
        max_output_bytes=limits.max_output_bytes,
    )
    raw = sandbox.run(job)
    return Execution(raw=raw, report=_parse_report(raw, token, [t.id for t in problem.tests]))


def _crash_reason(raw: RawResult) -> str:
    """A short, human-readable reason why the runner produced no valid report."""
    if raw.output_overflow:
        return "output limit exceeded"
    if raw.returncode is not None and raw.returncode < 0:
        return f"killed by signal {signal.Signals(-raw.returncode).name}"
    last_line = raw.stderr.strip().splitlines()[-1:] or [""]
    if last_line[0]:
        return last_line[0]
    return f"exited with code {raw.returncode} without a result"


def _test_status(
    test: TestCase, report: TestReport, check_input: bool
) -> tuple[TestStatus, str | None]:
    """Decide the status of one test. The comparison with `expected` happens only here."""
    if report.outcome == "timeout":
        return TestStatus.TIMEOUT, report.error
    if report.outcome == "error":
        return TestStatus.RUNTIME_ERROR, report.error
    if report.outcome == "bad_return":
        return TestStatus.WRONG_ANSWER, report.error
    if check_input and report.input_changed:
        return TestStatus.WRONG_ANSWER, INPUT_CHANGED_ERROR
    if outputs_match(report.actual, test.expected, test.compare):
        return TestStatus.PASSED, None
    return TestStatus.WRONG_ANSWER, None


def _test_result(
    test: TestCase, report: TestReport, reveal_hidden: bool, check_input: bool
) -> tuple[TestResult, str]:
    """Build one TestResult and return it with the stdout the student may see for this test."""
    status, error = _test_status(test, report, check_input)
    revealed = reveal_hidden or not test.hidden
    if not revealed and error is not None and status == TestStatus.RUNTIME_ERROR:
        # Keep only the exception type: a message could contain the hidden input.
        error = error.split(":", 1)[0]
    result = TestResult(
        test_id=test.id,
        hidden=test.hidden,
        status=status,
        error=error,
        revealed=revealed,
        input=test.input if revealed else None,
        expected=test.expected if revealed else None,
        actual=report.actual if revealed else None,
        duration_ms=report.duration_ms,
    )
    return result, report.stdout if revealed else ""


def _failed(
    problem: Problem,
    status: GradeStatus,
    raw: RawResult,
    *,
    compile_error: str | None = None,
    error: str | None = None,
    stdout: str = "",
) -> GradeResult:
    """A result with no per-test results and reward 0 (compile_error, crashed, total timeout)."""
    return GradeResult(
        problem_id=problem.id,
        problem_version=problem.version,
        status=status,
        passed=0,
        total=len(problem.tests),
        reward=0.0,
        tests=[],
        compile_error=compile_error,
        error=error,
        stdout=stdout,
        duration_ms=raw.duration_ms,
    )


def grade(
    problem: Problem,
    code: str,
    *,
    reveal_hidden: bool = False,
    limits: Limits | None = None,
    sandbox: Sandbox | None = None,
) -> GradeResult:
    """Grade one submission against one problem. The single entry point for all grading.

    reveal_hidden=False (for students) hides the input/expected/actual of hidden tests.
    Evals and RL use reveal_hidden=True.
    """
    missing = [test.id for test in problem.tests if not test.has_expected]
    if missing:
        raise GraderError(
            f"{problem.id}: tests without expected values: {', '.join(missing)} "
            "(run scripts/fill_expected.py)"
        )

    limits = _resolve_limits(problem, limits)
    execution = execute(problem, code, limits, sandbox)
    raw, report = execution.raw, execution.report

    if report is None:
        if raw.timed_out:
            total = limits.total_for(len(problem.tests))
            return _failed(
                problem, GradeStatus.TIMEOUT, raw, error=f"Total time limit exceeded ({total:g} s)"
            )
        return _failed(problem, GradeStatus.CRASHED, raw, error=_crash_reason(raw))

    truncation = TRUNCATION_NOTE if report.stdout_truncated else ""
    if not report.load.ok:
        return _failed(
            problem,
            GradeStatus.COMPILE_ERROR,
            raw,
            compile_error=report.load.error,
            stdout=report.load.stdout + truncation,
        )

    results: list[TestResult] = []
    stdout_parts = [report.load.stdout]
    for test, test_report in zip(problem.tests, report.tests, strict=True):
        result, visible_stdout = _test_result(
            test, test_report, reveal_hidden, problem.check_input_unchanged
        )
        results.append(result)
        stdout_parts.append(visible_stdout)

    passed = sum(1 for result in results if result.status == TestStatus.PASSED)
    first_failure = next((r for r in results if r.status != TestStatus.PASSED), None)
    status = GradeStatus.ACCEPTED if first_failure is None else GradeStatus(first_failure.status)
    return GradeResult(
        problem_id=problem.id,
        problem_version=problem.version,
        status=status,
        passed=passed,
        total=len(results),
        reward=round(passed / len(results), 4),
        tests=results,
        stdout="".join(stdout_parts) + truncation,
        duration_ms=raw.duration_ms,
    )


def grade_many(
    jobs: list[tuple[Problem, str]],
    *,
    workers: int = 4,
    reveal_hidden: bool = True,
    limits: Limits | None = None,
) -> list[GradeResult]:
    """Grade many submissions in parallel. Results are in the same order as `jobs`.

    Threads are enough here: each grade() spends its time waiting for a child process,
    and waiting doesn't hold Python's GIL.
    """

    def grade_one(job: tuple[Problem, str]) -> GradeResult:
        problem, code = job
        return grade(problem, code, reveal_hidden=reveal_hidden, limits=limits)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(grade_one, jobs))
