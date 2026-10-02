"""The database tables, as SQLAlchemy ORM classes (Week 3). See docs/database.md.

Two tables hold problems, like the two dist/ files:
- `problem_versions` (internal): a sealed copy of every problem version ever synced, hidden
  tests and solution included. Only the worker reads it. Rows are never updated.
- `problems` (student view): each problem's current version. This is what the API reads, so
  it never holds hidden tests.

The class names end in "Row" so they are never confused with the pydantic models
(`Problem`, `GradeResult`, ...).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    MetaData,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from codetutor.grader.models import GradeStatus, TestStatus
from codetutor.problems.schema import Difficulty

# Every constraint gets a predictable name (e.g. "ck_submissions_reward_in_range"), so a later
# migration can find it by name to change or drop it.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class of all tables. `Mapped[str]` means NOT NULL, `Mapped[str | None]` nullable."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Postgres types for plain Python annotations: text (no length limit), timestamps with a
    # time zone, and 8-byte floats (the same precision as a Python float).
    type_annotation_map = {
        str: Text(),
        datetime: DateTime(timezone=True),
        float: Double(),
    }


class JobStatus(StrEnum):
    """Where a submission is in the grading queue (Step 2's worker moves it along)."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"  # graded; the result columns are filled
    FAILED = "failed"  # gave up after retries (a system problem, not the student's mistake)


def _one_of(column: str, values: Iterable[StrEnum]) -> str:
    """SQL for a CHECK that `column` holds one of the enum's values, e.g. "x IN ('a', 'b')".

    The values come from our own enums, never from users, so writing them into SQL is safe.
    """
    return f"{column} IN ({', '.join(repr(value.value) for value in values)})"


class UserRow(Base):
    """A person who submits code. Week 3 has a name-only dev login (no password, not secure)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProblemVersionRow(Base):
    """A sealed copy of one problem version: everything, hidden tests and solution included.

    The worker grades against this copy, so a submission is always graded on the version the
    student saw. Sync refuses to change a stored copy: a changed problem needs a new version.
    """

    __tablename__ = "problem_versions"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    problem_id: Mapped[str] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str]  # sha256 of the problem folder (bank/build.py:content_hash)
    # Problem.model_dump(mode="json"). Postgres `json`, not `jsonb`: jsonb rewrites numbers
    # (the float 1e16 comes back as an int), and the grader treats 30 and 30.0 differently.
    problem: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ProblemRow(Base):
    """The current version of a problem, student view only. The API reads only this table."""

    __tablename__ = "problems"
    __table_args__ = (
        # The current version must be a stored copy.
        ForeignKeyConstraint(
            ["id", "version"], ["problem_versions.problem_id", "problem_versions.version"]
        ),
        CheckConstraint(_one_of("difficulty", Difficulty), name="difficulty_known"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    version: Mapped[int]
    module: Mapped[int]
    position: Mapped[int]  # "order" in problem.yaml; ORDER is a reserved word in SQL
    title: Mapped[str]
    difficulty: Mapped[str]
    # False when the problem folder was removed. Never deleted: old submissions point to it.
    active: Mapped[bool] = mapped_column(server_default=true())
    student_view: Mapped[dict[str, Any]] = mapped_column(JSON)  # Problem.to_student_view()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SubmissionRow(Base):
    """One submission. The row is also the grading job: Postgres is the queue (2026-10-02)."""

    __tablename__ = "submissions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["problem_id", "problem_version"],
            ["problem_versions.problem_id", "problem_versions.version"],
        ),
        CheckConstraint(_one_of("job_status", JobStatus), name="job_status_known"),
        CheckConstraint(_one_of("result_status", GradeStatus), name="result_status_known"),
        # A done job has a result, and only a done job has one.
        CheckConstraint(
            "(job_status = 'done') = (result_status IS NOT NULL)", name="result_iff_done"
        ),
        CheckConstraint(
            "result_status IS NULL OR (passed IS NOT NULL AND total IS NOT NULL "
            "AND reward IS NOT NULL AND stdout IS NOT NULL AND duration_ms IS NOT NULL "
            "AND grader_version IS NOT NULL)",
            name="result_complete",
        ),
        CheckConstraint("reward >= 0 AND reward <= 1", name="reward_in_range"),
        # The worker's claim query looks only at queued and running jobs, oldest id first.
        # A partial index holds only those rows, so it stays small while done/failed rows
        # pile up (worker/jobs.py, docs/worker.md).
        Index(
            "ix_submissions_claimable",
            "id",
            postgresql_where=text(_one_of("job_status", [JobStatus.QUEUED, JobStatus.RUNNING])),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    problem_id: Mapped[str]
    problem_version: Mapped[int]
    code: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # --- The job (the worker's bookkeeping, Step 2) ---
    job_status: Mapped[str] = mapped_column(server_default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    lease_expires_at: Mapped[datetime | None]  # a running job past this time may be retaken
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    last_error: Mapped[str | None]  # why grading failed (a system problem, never the student's)

    # --- The result: a GradeResult graded with reveal_hidden=False. NULL until done. ---
    result_status: Mapped[str | None]
    passed: Mapped[int | None]
    total: Mapped[int | None]
    reward: Mapped[float | None]
    compile_error: Mapped[str | None]
    error: Mapped[str | None]
    stdout: Mapped[str | None]
    duration_ms: Mapped[float | None]
    grader_version: Mapped[str | None]


class TestResultRow(Base):
    """One test of one graded submission: a TestResult from a reveal_hidden=False grading."""

    __test__ = False  # not a pytest test class, despite the name
    __tablename__ = "test_results"
    __table_args__ = (
        CheckConstraint(_one_of("status", TestStatus), name="status_known"),
        # The rule "hidden tests never reach the database", kept by the database itself: even
        # a bug in the worker can't store a hidden test's input or expected value.
        CheckConstraint("NOT (hidden AND revealed)", name="hidden_never_revealed"),
        CheckConstraint(
            "revealed OR (input IS NULL AND expected IS NULL AND actual IS NULL)",
            name="unrevealed_has_no_details",
        ),
    )

    submission_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("submissions.id", ondelete="CASCADE"), primary_key=True
    )
    test_id: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int]  # the test's place in GradeResult.tests (0 = first)
    hidden: Mapped[bool]
    revealed: Mapped[bool]
    status: Mapped[str]
    error: Mapped[str | None]
    # JSON null (a real value, e.g. expected None) and SQL NULL (no details stored) are
    # different here: unrevealed rows must have SQL NULL (see the CHECK above).
    input: Mapped[list[Any] | None] = mapped_column(JSON)
    expected: Mapped[Any] = mapped_column(JSON, nullable=True)
    actual: Mapped[Any] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[float]
