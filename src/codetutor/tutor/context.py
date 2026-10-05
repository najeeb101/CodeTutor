"""What the tutor knows about one hint request, turned into text (Week 4 Step 2, docs/tutor.md §3).

The model sees the student's side only: the problem text, the student's code and question, the
visible tests with the student's results, and the hidden tests **as counts**. It never sees
solution.py, hidden inputs or expected values, the bottom-out hint 3, or the student's print
output. `HintRequest` refuses a grade result that reveals a hidden test, so hidden details can't
reach a prompt by mistake.
"""

from __future__ import annotations

from dataclasses import dataclass

from codetutor.grader.models import GradeResult, GradeStatus, TestResult, TestStatus
from codetutor.problems import Problem

LEVELS = (1, 2, 3)  # 1-2: the model writes the hint; 3: the bottom-out reference hint
MAX_CODE_CHARS = 2000  # CS1 solutions are 300-800 characters; this keeps the prompt small
MAX_VALUE_CHARS = 200  # a returned value or error message is cut here
MAX_FAILED_SHOWN = 3  # failed visible tests shown in the prompt


@dataclass(frozen=True)
class HintRequest:
    """A student asks for a hint about `code` (the pipeline decides what the model sees)."""

    problem: Problem  # the full problem; only its student side goes into the prompt
    code: str
    level: int
    question: str | None = None
    result: GradeResult | None = None  # the grade of `code` (reveal_hidden=False), if any
    earlier_hints: tuple[str, ...] = ()  # hints already shown for this code, oldest first

    def __post_init__(self) -> None:
        if self.level not in LEVELS:
            raise ValueError(f"level must be one of {LEVELS}, not {self.level}")
        result = self.result
        if result is None:
            return
        if (result.problem_id, result.problem_version) != (self.problem.id, self.problem.version):
            raise ValueError(
                f"the result is for {result.problem_id} v{result.problem_version}, "
                f"not {self.problem.id} v{self.problem.version}"
            )
        if any(test.hidden and test.revealed for test in result.tests):
            raise ValueError("the result reveals a hidden test: grade with reveal_hidden=False")


def code_for_prompt(code: str) -> str:
    """The student's code, cut at MAX_CODE_CHARS (the prompt must stay small)."""
    if len(code) <= MAX_CODE_CHARS:
        return code.rstrip()
    return code[:MAX_CODE_CHARS].rstrip() + "\n# ... (the rest of the code was cut: too long)"


def describe_result(problem: Problem, result: GradeResult | None) -> str:
    """The student's test results as plain text: visible details, hidden counts only."""
    if result is None:
        return "The code has not been tested yet."
    if result.status == GradeStatus.COMPILE_ERROR:
        return f"The code does not run: {_cut(result.compile_error or 'syntax error')}"
    if not result.tests:  # crashed, or the whole run timed out
        reason = result.error or result.status.value
        return f"Grading stopped before any test finished: {_cut(reason)}"
    visible = [test for test in result.tests if not test.hidden]
    hidden = [test for test in result.tests if test.hidden]
    lines = [f"Visible tests: {_passed(visible)} of {len(visible)} passed."]
    failed = [test for test in visible if test.status != TestStatus.PASSED]
    lines += [f"- {_failure(problem, test)}" for test in failed[:MAX_FAILED_SHOWN]]
    more = len(failed) - MAX_FAILED_SHOWN
    if more > 0:
        lines.append(f"- ... and {more} more failed visible test{'s' if more > 1 else ''}")
    if hidden:
        lines.append(
            f"Hidden tests: {_passed(hidden)} of {len(hidden)} passed "
            "(their inputs and expected answers are secret)."
        )
    return "\n".join(lines)


def search_text(request: HintRequest) -> str:
    """What the note search looks for: the question, the exercise, its concepts, the failure."""
    problem = request.problem
    parts = [request.question.strip()] if request.question and request.question.strip() else []
    parts.append(problem.title)
    parts.append(", ".join(concept.value.replace("_", " ") for concept in problem.concepts))
    failure = _first_failure(request.result)
    if failure:
        parts.append(failure)
    return ". ".join(parts)


def _first_failure(result: GradeResult | None) -> str | None:
    """A short failure description for the search, e.g. "IndexError: list index out of range"."""
    if result is None or result.status == GradeStatus.ACCEPTED:
        return None
    if result.status == GradeStatus.COMPILE_ERROR:
        return f"syntax error {_first_line(result.compile_error)}"
    for test in result.tests:
        if test.status != TestStatus.PASSED:
            if test.error:
                return _first_line(test.error)
            return test.status.value.replace("_", " ")
    return result.status.value.replace("_", " ")


def _failure(problem: Problem, test: TestResult) -> str:
    """One failed visible test, e.g. "fizzbuzz(15) should return [...], but it returned [...]"."""
    args = ", ".join(repr(arg) for arg in test.input or [])
    call = f"{problem.function_name}({_cut(args)})"
    expected = _cut(repr(test.expected))
    if test.status == TestStatus.TIMEOUT:
        return f"{call} should return {expected}, but it took too long"
    if test.error:
        return f"{call} should return {expected}, but it failed: {_cut(test.error)}"
    return f"{call} should return {expected}, but it returned {_cut(repr(test.actual))}"


def _passed(tests: list[TestResult]) -> int:
    return sum(1 for test in tests if test.status == TestStatus.PASSED)


def _first_line(text: str | None) -> str:
    lines = (text or "").strip().splitlines()
    return _cut(lines[-1]) if lines else ""  # a traceback's last line names the error


def _cut(text: str) -> str:
    return text if len(text) <= MAX_VALUE_CHARS else text[:MAX_VALUE_CHARS] + "…"
