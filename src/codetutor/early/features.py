"""What we know about a student at the end of week `cutoff` (Week 8 Step 3a).

The one rule: only submissions made up to the cutoff are read. `prefix` cuts first, and every
feature is computed from the cut list, so later rows cannot leak in (a test pins this).
No labels and no outcomes: these are plain facts from the submissions table.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, time, timedelta

from codetutor.integrity.signals import SubmissionInfo
from codetutor.skill.load import first_attempts
from codetutor.skill.rasch import fit_rasch

WEEK = timedelta(days=7)
FEATURE_NAMES = (
    "first_try_share",  # accepted first tries / graded first tries
    "problems_tried",
    "tries_per_solved",  # submissions / (problems solved + 1)
    "activity_trend",  # submissions in the cutoff week minus submissions in week 1
    "days_since_last",  # from the last submission to the end of the cutoff week
    "rasch_skill",  # fitted on everyone's first tries up to the cutoff
)


def course_start(submissions: Sequence[SubmissionInfo]) -> datetime:
    """Midnight of the Monday of the earliest submission: week 1 starts here."""
    first = min(s.created_at for s in submissions)
    monday = first.date() - timedelta(days=first.weekday())
    return datetime.combine(monday, time.min, tzinfo=first.tzinfo)


def week_of(created_at: datetime, start: datetime) -> int:
    """1 for the first 7 days, 2 for the next 7, and so on."""
    return (created_at - start).days // 7 + 1


def prefix(
    submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime
) -> list[SubmissionInfo]:
    """The submissions made in weeks 1..cutoff."""
    return [s for s in submissions if week_of(s.created_at, start) <= cutoff]


def features_at(
    submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime
) -> dict[str, list[float]]:
    """One feature vector (order of FEATURE_NAMES) per student with a submission by the cutoff."""
    seen = prefix(submissions, cutoff, start)
    by_student: dict[str, list[SubmissionInfo]] = defaultdict(list)
    for s in seen:
        by_student[s.student].append(s)
    attempts = first_attempts(seen).responses
    skill = fit_rasch(attempts).skill if attempts else {}
    end = start + cutoff * WEEK
    vectors = {}
    for student, rows in sorted(by_student.items()):
        mine = [r for r in attempts if r.student == student]
        solved_first = sum(r.solved for r in mine)
        solved = {r.problem_id for r in rows if r.result_status == "accepted"}
        weeks = [week_of(r.created_at, start) for r in rows]
        last = max(r.created_at for r in rows)
        vectors[student] = [
            solved_first / len(mine) if mine else 0.0,
            float(len({r.problem_id for r in rows})),
            len(rows) / (len(solved) + 1),
            float(weeks.count(cutoff) - weeks.count(1)),
            (end - last).total_seconds() / 86400,
            skill.get(student, 0.0),
        ]
    return vectors
