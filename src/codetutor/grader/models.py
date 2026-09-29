"""Data models for the grader: limits, results, and what goes in and out of the sandbox.

All constants that control grading live here so they are easy to find and to override.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

# Bump whenever grading logic changes, so saved results say which grader produced them.
# 0.2.0: optional check that the function does not change its input (check_input_unchanged).
GRADER_VERSION = "0.2.0"

# Extra time allowed for starting Python and loading the submission (used for the automatic total).
STARTUP_MARGIN_S = 3.0
# A single return value larger than this (as JSON) counts as a wrong answer.
MAX_RETURN_BYTES = 1_000_000
# The parent keeps at most this much of the child's stdout / stderr. More = "output limit exceeded".
MAX_CHILD_STDOUT_BYTES = 32_000_000
MAX_CHILD_STDERR_BYTES = 64_000

_FROZEN = ConfigDict(extra="forbid", frozen=True)


class Limits(BaseModel):
    """Resource limits for one grading run."""

    model_config = _FROZEN

    per_test_timeout_s: Annotated[float, Field(gt=0)] = 2.0
    # None = automatic: n_tests * per_test_timeout_s + STARTUP_MARGIN_S. Automatic means normal
    # per-test timeouts can never add up to a total timeout (decision Q3).
    total_timeout_s: Annotated[float, Field(gt=0)] | None = None
    memory_mb: Annotated[int, Field(gt=0)] = 512
    max_output_bytes: Annotated[int, Field(ge=0)] = 64_000  # student print output kept
    max_file_mb: Annotated[int, Field(ge=0)] = 1

    def total_for(self, n_tests: int) -> float:
        """The total wall-clock limit for a run with `n_tests` tests."""
        if self.total_timeout_s is not None:
            return self.total_timeout_s
        return n_tests * self.per_test_timeout_s + STARTUP_MARGIN_S


class TestStatus(StrEnum):
    """Outcome of one test."""

    __test__ = False  # not a pytest test class

    PASSED = "passed"
    WRONG_ANSWER = "wrong_answer"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"


class GradeStatus(StrEnum):
    """Outcome of a whole submission."""

    ACCEPTED = "accepted"
    WRONG_ANSWER = "wrong_answer"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    COMPILE_ERROR = "compile_error"
    CRASHED = "crashed"


class TestResult(BaseModel):
    """Result of one test.

    If `revealed` is False (a hidden test, graded with reveal_hidden=False), `input`, `expected`
    and `actual` are None and `error` is shortened, so hidden tests can't leak.
    """

    model_config = _FROZEN
    __test__ = False

    test_id: str
    hidden: bool
    status: TestStatus
    error: str | None = None
    revealed: bool
    input: list[JsonValue] | None = None
    expected: JsonValue = None
    actual: JsonValue = None
    duration_ms: float


class GradeResult(BaseModel):
    """Result of grading one submission against one problem."""

    model_config = _FROZEN

    problem_id: str
    problem_version: int
    status: GradeStatus
    passed: int
    total: int
    # passed / total, rounded to 4 decimals. 0.0 for compile_error, crashed and total timeout.
    reward: float
    tests: list[TestResult]  # empty for compile_error, crashed and total timeout
    compile_error: str | None = None
    error: str | None = None  # reason for crashed / total timeout
    stdout: str  # the student's print output (truncated; hidden tests' output only if revealed)
    duration_ms: float
    grader_version: str = GRADER_VERSION


# --- What goes into and comes out of a sandbox ---


class SandboxTest(BaseModel):
    """A test as sent to the child: id and input only. Expected values never enter the child."""

    model_config = _FROZEN

    id: str
    input: list[JsonValue]


class SandboxJob(BaseModel):
    """Everything the runner needs. Serialized to JSON and written to the child's stdin."""

    model_config = _FROZEN

    token: str
    code: str
    function_name: str
    tests: list[SandboxTest]
    per_test_timeout_s: float
    total_timeout_s: float
    memory_mb: int
    max_file_mb: int
    max_output_bytes: int
    max_return_bytes: int = MAX_RETURN_BYTES


class RawResult(BaseModel):
    """What the sandbox observed. The grader turns this into a GradeResult."""

    model_config = _FROZEN

    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    output_overflow: bool
    duration_ms: float


# --- The runner's report (parsed from the child's stdout; untrusted, so it is validated) ---


class LoadReport(BaseModel):
    """Did the submission load, and what did it print while loading."""

    model_config = _FROZEN

    ok: bool
    error: str | None = None
    stdout: str = ""


class TestReport(BaseModel):
    """What happened in one test, as reported by the runner. No pass/fail: the parent decides."""

    model_config = _FROZEN
    __test__ = False

    id: str
    outcome: Literal["returned", "bad_return", "error", "timeout"]
    actual: JsonValue = None
    input_changed: bool = False  # only set when outcome == "returned"
    error: str | None = None
    stdout: str = ""
    duration_ms: float


class RunnerReport(BaseModel):
    """The full report the runner writes after the token."""

    model_config = _FROZEN

    load: LoadReport
    tests: list[TestReport]
    stdout_truncated: bool = False
