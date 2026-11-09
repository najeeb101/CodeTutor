"""The endpoints (docs/api.md). Thin: they call plain functions and turn our errors into HTTP
status codes. Plain `def` (not `async def`): FastAPI runs them in its thread pool, and our
database code is synchronous like the rest of the project.

The API reads only `problems` (student view), `users`, `submissions`, `test_results` and
`hints` (never the trace columns), never the sealed problem copies with the hidden tests. A
test checks that no file in this package names that table or its class (tests/test_api.py).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Path, Query, Request, Response
from sqlalchemy import select, text

from codetutor.api.auth import (
    SESSION_COOKIE,
    SESSION_DAYS,
    create_guest,
    end_session,
    guests_in_last_hour,
    new_session,
)
from codetutor.api.deps import LimitsDep, SessionDep, UserDep
from codetutor.api.guards import client_ip
from codetutor.api.hints import (
    HintConflictError,
    NotFoundError,
    create_hint,
    get_own_hint,
    list_hints,
    rate_hint,
)
from codetutor.api.schemas import (
    FAILED_MESSAGE,
    MAX_ID,
    HintCreated,
    HintIn,
    HintOut,
    LoginIn,
    ProblemOut,
    ProblemSummary,
    RatingIn,
    ResultOut,
    SubmissionCreated,
    SubmissionIn,
    SubmissionOut,
    SubmissionSummary,
    UserOut,
)
from codetutor.api.submissions import (
    BUSY_RETRY_AFTER_S,
    RateLimitedError,
    ServerBusyError,
    create_submission,
    get_own_submission,
    list_submissions,
)
from codetutor.db.models import JobStatus, ProblemRow
from codetutor.db.users import get_or_create_user
from codetutor.problems.schema import StudentProblem
from codetutor.worker.jobs import (
    InvalidSubmissionError,
    ProblemChangedError,
    UnknownProblemError,
    load_grade_result,
)

MAX_LIST_LIMIT = 100

router = APIRouter(prefix="/api")


@router.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    """200 if the API can reach the database (503 otherwise, from the app's error handler)."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.post("/login")
def login(body: LoginIn, session: SessionDep, request: Request) -> UserOut:
    """Dev login (NOT secure): find or create the user with this name. Only with dev login on."""
    if not request.app.state.dev_login:
        raise HTTPException(404, "Not Found")
    user_id = get_or_create_user(session, body.name)
    session.commit()
    return UserOut(id=user_id, name=body.name)


@router.post("/guest")
def start_guest(
    session: SessionDep, request: Request, response: Response, limits: LimitsDep
) -> UserOut:
    """Start as a new guest: a new user and a session cookie (api/auth.py)."""
    if guests_in_last_hour(session) >= limits.guests_per_hour:
        raise HTTPException(
            503,
            "too many new guests right now; try again later",
            headers={"Retry-After": str(BUSY_RETRY_AFTER_S)},
        )
    socket_host = request.client.host if request.client else "unknown"
    ip = client_ip(request.headers, socket_host, request.app.state.trusted_proxy_hops)
    wait_s = request.app.state.guest_ips.hit(ip)
    if wait_s is not None:
        raise HTTPException(
            429, "too many new guests from your address", headers={"Retry-After": str(wait_s)}
        )
    user = create_guest(session)
    token = new_session(session, user.id)
    session.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        path="/api",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return UserOut(id=user.id, name=user.name)


@router.get("/me")
def me(user: UserDep) -> UserOut:
    """Who is logged in (the page can't read the HttpOnly cookie itself)."""
    return UserOut(id=user.id, name=user.name)


@router.post("/logout")
def logout(
    session: SessionDep,
    response: Response,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE, max_length=200)] = None,
) -> dict[str, str]:
    """End the session: its row is deleted, so an old copy of the cookie stops working too."""
    if token is not None:
        end_session(session, token)
        session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/api", secure=True, httponly=True, samesite="lax")
    return {"status": "logged out"}


@router.get("/problems")
def list_problems(session: SessionDep) -> list[ProblemSummary]:
    """All active problems, by module, then by their order in the module."""
    rows = session.scalars(
        select(ProblemRow)
        .where(ProblemRow.active)
        .order_by(ProblemRow.module, ProblemRow.position, ProblemRow.id)
    )
    return [
        ProblemSummary(
            id=row.id,
            title=row.title,
            module=row.module,
            module_name=row.student_view["module_name"],
            order=row.position,
            difficulty=row.difficulty,
        )
        for row in rows
    ]


@router.get("/problems/{problem_id}")
def get_problem(problem_id: str, session: SessionDep) -> ProblemOut:
    """The student view of one active problem: no hints, solutions or hidden tests."""
    row = session.get(ProblemRow, problem_id)
    if row is None or not row.active:
        raise HTTPException(404, f"no problem {problem_id!r}")
    return ProblemOut.from_student_view(StudentProblem.model_validate(row.student_view))


@router.post("/submissions", status_code=202)
def submit(
    body: SubmissionIn,
    user: UserDep,
    session: SessionDep,
    limits: LimitsDep,
    response: Response,
) -> SubmissionCreated:
    """Queue code for grading. 202 Accepted: the worker grades it later; poll the Location."""
    try:
        submission_id = create_submission(
            session,
            user.id,
            body.problem_id,
            body.problem_version,
            body.code,
            limits,
            editor_stats=body.editor_stats.model_dump() if body.editor_stats else None,
        )
    except RateLimitedError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc
    except ServerBusyError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc
    except UnknownProblemError as exc:
        raise HTTPException(404, f"no problem {body.problem_id!r}") from exc
    except ProblemChangedError as exc:
        raise HTTPException(
            409,
            f"this problem changed (now version {exc.current_version}); reload it and submit again",
        ) from exc
    except InvalidSubmissionError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    response.headers["Location"] = f"/api/submissions/{submission_id}"
    return SubmissionCreated(id=submission_id, job_status=JobStatus.QUEUED)


@router.get("/submissions/{submission_id}")
def get_submission(
    submission_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    user: UserDep,
    session: SessionDep,
) -> SubmissionOut:
    """One of my submissions: status, code and result. 404 also for other users' submissions."""
    submission = get_own_submission(session, user.id, submission_id)
    if submission is None:
        raise HTTPException(404, f"no submission {submission_id}")
    summary = SubmissionSummary.model_validate(submission)
    result = load_grade_result(session, submission.id)
    return SubmissionOut(
        **summary.model_dump(),
        code=submission.code,
        finished_at=submission.finished_at,
        # Never `last_error` itself: it can contain internal details.
        message=FAILED_MESSAGE if submission.job_status == JobStatus.FAILED else None,
        result=None if result is None else ResultOut.from_result(result),
    )


@router.get("/submissions")
def my_submissions(
    user: UserDep,
    session: SessionDep,
    problem_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 20,
) -> list[SubmissionSummary]:
    """My newest submissions (optionally for one problem), newest first."""
    rows = list_submissions(session, user.id, problem_id=problem_id, limit=limit)
    return [SubmissionSummary.model_validate(row) for row in rows]


@router.post("/hints", status_code=202)
def ask_for_hint(
    body: HintIn,
    user: UserDep,
    session: SessionDep,
    limits: LimitsDep,
    response: Response,
) -> HintCreated:
    """Queue a hint request. 202 Accepted: the tutor worker answers it; poll the Location."""
    try:
        hint_id = create_hint(
            session,
            user.id,
            problem_id=body.problem_id,
            problem_version=body.problem_version,
            level=body.level,
            limits=limits,
            question=body.question,
            submission_id=body.submission_id,
            code=body.code,
        )
    except RateLimitedError as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc
    except ServerBusyError as exc:
        raise HTTPException(503, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except UnknownProblemError as exc:
        raise HTTPException(404, f"no problem {body.problem_id!r}") from exc
    except ProblemChangedError as exc:
        raise HTTPException(
            409, f"this problem changed (now version {exc.current_version}); reload it"
        ) from exc
    except HintConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (InvalidSubmissionError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    response.headers["Location"] = f"/api/hints/{hint_id}"
    return HintCreated(id=hint_id, job_status=JobStatus.QUEUED)


@router.get("/hints/{hint_id}")
def get_hint(
    hint_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    user: UserDep,
    session: SessionDep,
) -> HintOut:
    """One of my hints: its status, then its text. 404 also for other users' hints."""
    row = get_own_hint(session, user.id, hint_id)
    if row is None:
        raise HTTPException(404, f"no hint {hint_id}")
    return HintOut.model_validate(row)


@router.get("/hints")
def my_hints(
    user: UserDep,
    session: SessionDep,
    problem_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIST_LIMIT)] = 20,
) -> list[HintOut]:
    """My newest hints (optionally for one problem), newest first."""
    rows = list_hints(session, user.id, problem_id=problem_id, limit=limit)
    return [HintOut.model_validate(row) for row in rows]


@router.put("/hints/{hint_id}/rating")
def rate(
    hint_id: Annotated[int, Path(ge=1, le=MAX_ID)],
    body: RatingIn,
    user: UserDep,
    session: SessionDep,
) -> HintOut:
    """👍 (1) or 👎 (-1) for one of my finished hints; a new rating replaces the old one."""
    try:
        row = rate_hint(session, user.id, hint_id, body.rating)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except HintConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return HintOut.model_validate(row)
