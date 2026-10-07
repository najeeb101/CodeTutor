"""First-attempt responses from the submissions in a database (Week 5 Step 3).

Why only the first try: later tries are practice (the simulator makes them easier, real
students learn from the result), so mixing them in would blur "skill minus difficulty".
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from codetutor.integrity.signals import SubmissionInfo
from codetutor.skill.rasch import Response


@dataclass(frozen=True)
class FirstAttempts:
    """The responses, and what was left out (so the report can say it)."""

    responses: list[Response]
    ungraded: int  # first submissions without a result yet
    excluded: int  # first submissions dropped by the caller's `exclude`


def first_attempts(
    submissions: Sequence[SubmissionInfo], exclude: Collection[int] = ()
) -> FirstAttempts:
    """One response per (student, problem): the earliest submission (time, then id).

    `exclude`: submission ids to leave out (e.g. the ones the integrity checks say need
    review). A student's first try is a pair that is left out entirely, never replaced by
    their second try.
    """
    first: dict[tuple[str, str], SubmissionInfo] = {}
    for s in sorted(submissions, key=lambda s: (s.created_at, s.id)):
        first.setdefault((s.student, s.problem_id), s)
    skip = set(exclude)
    responses = []
    ungraded = excluded = 0
    for (student, problem), s in sorted(first.items()):
        if s.id in skip:
            excluded += 1
        elif s.result_status is None:
            ungraded += 1
        else:
            responses.append(Response(student, problem, s.result_status == "accepted"))
    return FirstAttempts(responses, ungraded, excluded)
