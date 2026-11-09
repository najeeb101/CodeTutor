"""What the API accepts and returns (pydantic models; docs/api.md).

Every response model is an allow-list: a field that is not listed here never reaches a client,
even if a query loaded it (e.g. `last_error`, `attempts`). Problems and results extend the
existing models (`StudentProblem`, `GradeResult`) with display text only, so there is one
definition of each.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from codetutor.db.models import HintSource, JobStatus
from codetutor.grader.models import GradeResult, GradeStatus, TestResult
from codetutor.problems.schema import PROBLEM_ID_PATTERN, Difficulty, StudentProblem, VisibleTest
from codetutor.tutor.jobs import MAX_QUESTION_CHARS

MAX_REPR_CHARS = 500  # display text is cut here (a returned value can be up to 1 MB)
MAX_NAME_CHARS = 40
# Postgres bigint: a larger id in a header or URL is a 422, not a database error (500).
MAX_ID = 2**63 - 1
# Shown instead of `last_error`, which can hold internal details (docs/worker.md §7).
FAILED_MESSAGE = (
    "Grading failed because of a problem on our side, not your code. Please submit again."
)

# Shown instead of a hint job's `last_error` (same reason).
HINT_FAILED_MESSAGE = (
    "The tutor could not answer because of a problem on our side, not your code. Please ask again."
)

_REQUEST = ConfigDict(extra="forbid")  # an unknown field in a request is an error (typos)


def _cut(text: str) -> str:
    return text if len(text) <= MAX_REPR_CHARS else text[: MAX_REPR_CHARS - 1] + "…"


def py_repr(value: JsonValue) -> str:
    """A value as Python prints it, e.g. 32.0, 'Fizz', None, [1, True].

    The browser can't do this from JSON: JavaScript has one number type, so JSON.parse("32.0")
    gives 32, and the grader treats 30 and 30.0 differently. The eval prompt shows models the
    same repr text (evals/prompt.py).
    """
    return _cut(repr(value))


def py_args(args: list[JsonValue]) -> str:
    """A call's arguments as Python text, e.g. "[1, 2], 3" for f([1, 2], 3)."""
    return _cut(", ".join(repr(arg) for arg in args))


class LoginIn(BaseModel):
    """Dev login: a name only (NOT secure). Any language; spaces around it are removed."""

    model_config = _REQUEST

    name: str

    @field_validator("name")
    @classmethod
    def _clean_name(cls, name: str) -> str:
        name = name.strip()
        if not 1 <= len(name) <= MAX_NAME_CHARS:
            raise ValueError(f"name must have 1 to {MAX_NAME_CHARS} characters")
        # Cc: control characters (NUL, newline, ...). Cs: lone surrogates, which JSON allows
        # ("\ud800") but Postgres can't store.
        if any(unicodedata.category(char) in ("Cc", "Cs") for char in name):
            raise ValueError("name must not contain control characters")
        return name


class UserOut(BaseModel):
    """The logged-in user (the session cookie identifies them; dev login: X-User-Id)."""

    id: int
    name: str


class ExampleOut(VisibleTest):
    """A visible test with Python display text, e.g. args_repr "0", expected_repr "32.0"."""

    args_repr: str
    expected_repr: str


class ProblemOut(StudentProblem):
    """The student view of a problem; each example also carries its Python display text."""

    examples: list[ExampleOut]

    @classmethod
    def from_student_view(cls, problem: StudentProblem) -> ProblemOut:
        examples = [
            ExampleOut(
                **example.model_dump(),
                args_repr=py_args(example.input),
                expected_repr=py_repr(example.expected),
            )
            for example in problem.examples
        ]
        return cls(**problem.model_dump(exclude={"examples"}), examples=examples)


class TestOut(TestResult):
    """One test result. A revealed test also carries Python display text; a hidden one never.

    `actual_repr` is null when the test has an error: the error message says what happened.
    """

    __test__ = False  # not a pytest test class, despite the name

    args_repr: str | None = None
    expected_repr: str | None = None
    actual_repr: str | None = None


class ResultOut(GradeResult):
    """A grading result (reveal_hidden=False) with display text for the revealed tests."""

    tests: list[TestOut]

    @classmethod
    def from_result(cls, result: GradeResult) -> ResultOut:
        tests = [TestOut(**test.model_dump(), **_display_text(test)) for test in result.tests]
        return cls(**result.model_dump(exclude={"tests"}), tests=tests)


def _display_text(test: TestResult) -> dict[str, Any]:
    if not test.revealed:
        return {}  # hidden: no input, expected or actual, so no text either
    return {
        "args_repr": py_args(test.input or []),
        "expected_repr": py_repr(test.expected),
        "actual_repr": None if test.error else py_repr(test.actual),
    }


class ProblemSummary(BaseModel):
    """One row of the problem list."""

    id: str
    title: str
    module: int
    module_name: str
    order: int
    difficulty: Difficulty


# Upper bounds for the editor summary: generous, only there to keep nonsense out of the database.
MAX_EDITOR_MS = 30 * 24 * 3600 * 1000  # a page left open for 30 days
MAX_EDITOR_COUNT = 10_000_000  # characters or edits (more than the 50,000-character code limit,
# because deleted text was typed too)
_Millis = Annotated[int, Field(ge=0, le=MAX_EDITOR_MS, strict=True)]
_Count = Annotated[int, Field(ge=0, le=MAX_EDITOR_COUNT, strict=True)]


class EditorStats(BaseModel):
    """What the web editor saw since the page was opened or the last submit (Week 5 Step 0).

    Times and counts only, no keystrokes. The browser sends it, so it can be faked: it is a
    signal for a human (docs/api.md), never proof. `strict=True`: "5" or 5.0 is refused, so
    every stored value is a plain integer.
    """

    model_config = _REQUEST

    since_open_ms: _Millis  # this page view (a draft from an earlier visit: restored_draft)
    active_ms: _Millis  # from the first edit to the submit (0 if nothing was edited)
    typed_chars: _Count  # characters inserted by edits that were not pastes
    pasted_chars: _Count
    paste_count: _Count
    largest_paste_chars: _Count
    edit_count: _Count
    restored_draft: Annotated[bool, Field(strict=True)]  # the code came from a saved draft

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.largest_paste_chars > self.pasted_chars:
            raise ValueError("largest_paste_chars can't be more than pasted_chars")
        if (self.paste_count == 0) != (self.pasted_chars == 0):
            raise ValueError("pasted_chars must be 0 exactly when paste_count is 0")
        if self.active_ms > self.since_open_ms:
            raise ValueError("active_ms can't be more than since_open_ms")
        return self


class SubmissionIn(BaseModel):
    """A submission. `problem_version` is the version the student saw (from GET problem)."""

    model_config = _REQUEST

    # The problem id format (also keeps text Postgres can't store, like "\ud800", out)
    problem_id: Annotated[str, Field(pattern=PROBLEM_ID_PATTERN)]
    problem_version: Annotated[int, Field(ge=1)]
    code: str  # length and characters are checked by enqueue_submission (one place)
    editor_stats: EditorStats | None = None  # the web UI sends it; scripts don't


class SubmissionCreated(BaseModel):
    """Answer to a submit: the job is queued; poll GET /api/submissions/{id} for the result."""

    id: int
    job_status: JobStatus


class SubmissionSummary(BaseModel):
    """One row of "my submissions". The result columns are null until the job is done."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: str
    problem_version: int
    created_at: datetime
    job_status: JobStatus
    result_status: GradeStatus | None
    passed: int | None
    total: int | None
    reward: float | None


class SubmissionOut(SubmissionSummary):
    """One submission with its code and full result (graded with reveal_hidden=False)."""

    code: str
    finished_at: datetime | None
    message: str | None  # FAILED_MESSAGE when job_status is "failed", else null
    result: ResultOut | None  # null until the job is done


class HintIn(BaseModel):
    """A hint request, about exactly one of: my graded submission, or code not graded yet.

    `problem_version` is the version the student saw. Levels go in order (1, 2, then the last
    hint 3); the server checks it.
    """

    model_config = _REQUEST

    problem_id: Annotated[str, Field(pattern=PROBLEM_ID_PATTERN)]
    problem_version: Annotated[int, Field(ge=1)]
    level: Annotated[int, Field(ge=1, le=3)]
    question: str | None = None
    submission_id: Annotated[int | None, Field(ge=1, le=MAX_ID)] = None
    code: str | None = None  # length and characters are checked by enqueue_hint

    @field_validator("question")
    @classmethod
    def _clean_question(cls, question: str | None) -> str | None:
        if question is None or not question.strip():
            return None
        question = question.strip()
        if len(question) > MAX_QUESTION_CHARS:
            raise ValueError(f"a question has at most {MAX_QUESTION_CHARS} characters")
        # Line breaks and tabs are fine in a question; other control characters and lone
        # surrogates are not (Postgres can't store NUL or "\ud800").
        bad = {"Cc", "Cs"}
        if any(unicodedata.category(c) in bad and c not in "\n\t" for c in question):
            raise ValueError("the question must not contain control characters")
        return question

    @model_validator(mode="after")
    def _one_subject(self) -> Self:
        if (self.submission_id is None) == (self.code is None):
            raise ValueError("send exactly one of submission_id and code")
        return self


class HintCreated(BaseModel):
    """Answer to a hint request: queued; poll GET /api/hints/{id} for the hint."""

    id: int
    job_status: JobStatus


class HintOut(BaseModel):
    """One of my hints. Never the trace: blocked attempts can contain solution code (D7)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: str
    problem_version: int
    submission_id: int | None
    level: int
    question: str | None
    created_at: datetime
    job_status: JobStatus
    text: str | None  # null until done
    # "model": the tutor wrote it; "fallback" / "reference": the teacher's own hint
    source: HintSource | None
    rating: int | None
    message: str | None = None  # HINT_FAILED_MESSAGE when job_status is "failed"

    @model_validator(mode="after")
    def _failed_message(self) -> Self:
        if self.job_status == JobStatus.FAILED:
            self.message = HINT_FAILED_MESSAGE
        return self


class RatingIn(BaseModel):
    """👍 (1) or 👎 (-1) for a hint. A new rating replaces the old one."""

    model_config = _REQUEST

    rating: Literal[1, -1]
