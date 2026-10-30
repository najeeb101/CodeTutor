"""The instructor dashboard's data (Week 8 Step 1). Read-only; see docs/api.md §8.

Everything here is for a teacher and nothing is a grade: the skill numbers say who may need
help, and a flag is a reason to look, never a verdict (docs/integrity.md). Students never reach
these routes: they need `X-Instructor-Token`, a shared dev token from the environment (NOT real
authentication; it is the one thing to replace before hosting).

Estimates are computed on every request from the submissions (a class is tens of students),
so nothing is stored and nothing can go stale. This is the only API module that reads
`integrity_flags` and the student names of other students. No route returns code.
"""

from __future__ import annotations

import hmac
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from codetutor.api.deps import SessionDep
from codetutor.api.schemas import MAX_ID
from codetutor.db.models import IntegrityFlagRow, ProblemRow, SubmissionRow, UserRow
from codetutor.early.served import risk_scores
from codetutor.integrity.signals import FlagKind, SubmissionInfo, needs_review
from codetutor.settings import instructor_token
from codetutor.skill.load import first_attempts
from codetutor.skill.rasch import RaschFit, fit_rasch

DECIMALS = 2


def instructor_only(
    token: Annotated[str | None, Header(alias="X-Instructor-Token", max_length=200)] = None,
) -> None:
    """Let the request through only with the right token (503 if no token is configured)."""
    expected = instructor_token()
    if expected is None:
        raise HTTPException(503, "the instructor dashboard is off: set INSTRUCTOR_TOKEN")
    if token is None:
        raise HTTPException(401, "send the instructor token in the X-Instructor-Token header")
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(403, "wrong instructor token")


router = APIRouter(prefix="/api/instructor", dependencies=[Depends(instructor_only)])


class OverviewOut(BaseModel):
    students: int
    problems: int
    submissions: int
    graded: int
    accepted_share: float | None  # of graded submissions
    first_try_solve_share: float | None  # of first tries that are graded
    students_to_review: int  # students with at least one submission that needs review
    submissions_to_review: int
    flags_computed_at: datetime | None  # None: the integrity job never ran
    skill_fit_settled: bool | None  # None: nothing to fit
    risk_available: bool  # False until the class has a submission in week 3 or later


class StudentRow(BaseModel):
    id: int
    name: str
    submissions: int
    problems_tried: int
    problems_solved: int  # at any try
    first_try_solve_share: float | None
    last_active: datetime | None
    skill: float | None  # Rasch, higher = more skilled; None: no graded first try
    submissions_to_review: int
    # Early-warning score (0..1, higher = may struggle later), from weeks 1-3 only. A reason to
    # check in, never a verdict. None: too early in the course, or no work in weeks 1-3.
    risk: float | None


class StudentProblemRow(BaseModel):
    problem_id: str
    title: str
    tries: int
    solved: bool
    solved_on_first_try: bool | None  # None: the first try is not graded yet


class FlagOut(BaseModel):
    submission_id: int
    problem_id: str
    kind: str
    reason: str  # the sentence for the teacher
    value: float
    needs_review: bool  # the submission as a whole (one entry signal + one content signal)
    created_at: datetime  # when the integrity job wrote it


class StudentDetail(StudentRow):
    problems: list[StudentProblemRow]
    flags: list[FlagOut]


class ProblemStat(BaseModel):
    id: str
    title: str
    module: int
    declared_difficulty: str
    students: int  # who tried it
    first_try_solve_share: float | None
    estimated_difficulty: float | None  # Rasch, higher = harder


@dataclass
class ClassData:
    """Everything the four routes need, read once per request."""

    submissions: list[tuple[int, int, str, str, datetime, str | None]] = field(default_factory=list)
    users: dict[int, str] = field(default_factory=dict)
    problems: dict[str, ProblemRow] = field(default_factory=dict)
    flag_rows: list[IntegrityFlagRow] = field(default_factory=list)
    first_try: dict[tuple[str, str], bool] = field(default_factory=dict)  # (name, problem)
    fit: RaschFit | None = None
    review_ids: set[int] = field(default_factory=set)
    risk: dict[str, float] | None = None  # by student name; None: too early


def load_class(session: Session) -> ClassData:
    """Read the class: users, problems, submissions (never their code), flags, and the fit."""
    data = ClassData()
    data.users = dict(session.execute(select(UserRow.id, UserRow.name)).all())
    data.problems = {p.id: p for p in session.scalars(select(ProblemRow).where(ProblemRow.active))}
    data.submissions = [
        (sid, uid, data.users[uid], pid, created, status)
        for sid, uid, pid, created, status in session.execute(
            select(
                SubmissionRow.id,
                SubmissionRow.user_id,
                SubmissionRow.problem_id,
                SubmissionRow.created_at,
                SubmissionRow.result_status,
            ).order_by(SubmissionRow.created_at, SubmissionRow.id)
        )
    ]
    data.flag_rows = list(
        session.scalars(select(IntegrityFlagRow).order_by(IntegrityFlagRow.submission_id))
    )
    kinds: dict[int, list[FlagKind]] = defaultdict(list)
    for row in data.flag_rows:
        kinds[row.submission_id].append(FlagKind(row.kind))
    data.review_ids = {sid for sid, found in kinds.items() if needs_review(found)}
    # `first_attempts` is the one rule for "a first try" (Week 5); it asks for a SubmissionInfo,
    # which has no use for the code or the function name here.
    infos = [
        SubmissionInfo(sid, name, pid, "", created, "", None, status)
        for sid, _uid, name, pid, created, status in data.submissions
    ]
    data.risk = risk_scores(infos)
    attempts = first_attempts(infos)
    data.first_try = {(r.student, r.problem): r.solved for r in attempts.responses}
    data.fit = fit_rasch(attempts.responses) if attempts.responses else None
    return data


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, DECIMALS) if whole else None


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, DECIMALS)


def student_rows(data: ClassData) -> list[StudentRow]:
    """One row per user who has submitted, teachers' attention first (most to review)."""
    per_user: dict[int, list[tuple[int, str, datetime, str | None]]] = defaultdict(list)
    for sid, uid, _name, pid, created, status in data.submissions:
        per_user[uid].append((sid, pid, created, status))
    rows = []
    for uid, subs in per_user.items():
        name = data.users[uid]
        tried = {pid for _sid, pid, _c, _s in subs}
        solved = {pid for _sid, pid, _c, status in subs if status == "accepted"}
        firsts = [ok for (who, _pid), ok in data.first_try.items() if who == name]
        rows.append(
            StudentRow(
                id=uid,
                name=name,
                submissions=len(subs),
                problems_tried=len(tried),
                problems_solved=len(solved),
                first_try_solve_share=_share(sum(firsts), len(firsts)),
                last_active=max(created for _sid, _pid, created, _s in subs),
                skill=_rounded(data.fit.skill.get(name)) if data.fit else None,
                submissions_to_review=sum(sid in data.review_ids for sid, *_ in subs),
                risk=_rounded(data.risk.get(name)) if data.risk else None,
            )
        )
    return sorted(rows, key=lambda r: (-r.submissions_to_review, r.name))


def overview(data: ClassData) -> OverviewOut:
    """The class in one box."""
    graded = [s for s in data.submissions if s[5] is not None]
    accepted = sum(s[5] == "accepted" for s in graded)
    review_users = {uid for sid, uid, *_ in data.submissions if sid in data.review_ids}
    flags_at = max((row.created_at for row in data.flag_rows), default=None)
    return OverviewOut(
        students=len({s[1] for s in data.submissions}),
        problems=len(data.problems),
        submissions=len(data.submissions),
        graded=len(graded),
        accepted_share=_share(accepted, len(graded)),
        first_try_solve_share=_share(sum(data.first_try.values()), len(data.first_try)),
        students_to_review=len(review_users),
        submissions_to_review=len(data.review_ids),
        flags_computed_at=flags_at,
        skill_fit_settled=data.fit.converged if data.fit else None,
        risk_available=data.risk is not None,
    )


def problem_stats(data: ClassData) -> list[ProblemStat]:
    """Declared against measured difficulty, in the order students see the problems."""
    tried: dict[str, set[str]] = defaultdict(set)
    for _sid, _uid, name, pid, _c, _s in data.submissions:
        tried[pid].add(name)
    stats = []
    for problem in sorted(data.problems.values(), key=lambda p: (p.module, p.position, p.id)):
        firsts = [ok for (_who, pid), ok in data.first_try.items() if pid == problem.id]
        stats.append(
            ProblemStat(
                id=problem.id,
                title=problem.title,
                module=problem.module,
                declared_difficulty=problem.difficulty,
                students=len(tried[problem.id]),
                first_try_solve_share=_share(sum(firsts), len(firsts)),
                estimated_difficulty=(
                    _rounded(data.fit.difficulty.get(problem.id)) if data.fit else None
                ),
            )
        )
    return stats


def student_detail(data: ClassData, student_id: int) -> StudentDetail | None:
    """One student: the problems they tried and every flag, reasons included."""
    row = next((r for r in student_rows(data) if r.id == student_id), None)
    if row is None:
        return None
    tries: dict[str, list[str | None]] = defaultdict(list)
    for _sid, uid, _name, pid, _c, status in data.submissions:
        if uid == student_id:
            tries[pid].append(status)
    problems = []
    for pid, statuses in sorted(tries.items()):
        known = data.problems.get(pid)
        problems.append(
            StudentProblemRow(
                problem_id=pid,
                title=known.title if known else pid,
                tries=len(statuses),
                solved="accepted" in statuses,
                solved_on_first_try=data.first_try.get((row.name, pid)),
            )
        )
    own = {sid: pid for sid, uid, _n, pid, _c, _s in data.submissions if uid == student_id}
    flags = [
        FlagOut(
            submission_id=f.submission_id,
            problem_id=own[f.submission_id],
            kind=f.kind,
            reason=f.reason,
            value=round(f.value, 3),
            needs_review=f.submission_id in data.review_ids,
            created_at=f.created_at,
        )
        for f in data.flag_rows
        if f.submission_id in own
    ]
    flags.sort(key=lambda f: (not f.needs_review, f.submission_id, f.kind))
    return StudentDetail(**row.model_dump(), problems=problems, flags=flags)


@router.get("/overview")
def get_overview(session: SessionDep) -> OverviewOut:
    """The class at a glance."""
    return overview(load_class(session))


@router.get("/students")
def get_students(session: SessionDep) -> list[StudentRow]:
    """Every student who has submitted, those with something to review first."""
    return student_rows(load_class(session))


@router.get("/students/{student_id}")
def get_student(
    session: SessionDep, student_id: Annotated[int, Path(ge=1, le=MAX_ID)]
) -> StudentDetail:
    """One student's problems and flags (never their code)."""
    found = student_detail(load_class(session), student_id)
    if found is None:
        raise HTTPException(404, "no such student (or they have not submitted anything)")
    return found


@router.get("/problems")
def get_problems(session: SessionDep) -> list[ProblemStat]:
    """Each problem's declared difficulty next to what the first tries say."""
    return problem_stats(load_class(session))
