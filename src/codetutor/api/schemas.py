"""What the API accepts and returns (pydantic models; docs/api.md).

Every response model is an allow-list: a field that is not listed here never reaches a client,
even if a query loaded it (e.g. `last_error`, `attempts`). Problems and results reuse the
existing models (`StudentProblem`, `GradeResult`), so there is one definition of each.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from codetutor.db.models import JobStatus
from codetutor.grader.models import GradeResult, GradeStatus
from codetutor.problems.schema import PROBLEM_ID_PATTERN, Difficulty

MAX_NAME_CHARS = 40
# Postgres bigint: a larger id in a header or URL is a 422, not a database error (500).
MAX_ID = 2**63 - 1
# Shown instead of `last_error`, which can hold internal details (docs/worker.md §7).
FAILED_MESSAGE = (
    "Grading failed because of a problem on our side, not your code. Please submit again."
)

_REQUEST = ConfigDict(extra="forbid")  # an unknown field in a request is an error (typos)


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
    """The logged-in user. The client sends `id` back as the X-User-Id header."""

    id: int
    name: str


class ProblemSummary(BaseModel):
    """One row of the problem list."""

    id: str
    title: str
    module: int
    module_name: str
    order: int
    difficulty: Difficulty


class SubmissionIn(BaseModel):
    """A submission. `problem_version` is the version the student saw (from GET problem)."""

    model_config = _REQUEST

    # The problem id format (also keeps text Postgres can't store, like "\ud800", out)
    problem_id: Annotated[str, Field(pattern=PROBLEM_ID_PATTERN)]
    problem_version: Annotated[int, Field(ge=1)]
    code: str  # length and characters are checked by enqueue_submission (one place)


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
    result: GradeResult | None  # null until the job is done
