"""The integrity signals (Week 5 Step 2b, docs/integrity.md §2): signals for a human, never a
punishment (brief principle 6).

Four signals, in two groups:
- how the code got in (entry): `paste` (one big paste) and `fast_typing` (typed faster than
  a person thinks);
- what the code is (content): `same_as_student` (the same structure as another student's
  earlier code) and `same_as_ai` (the same structure as a known AI answer).
A submission **needs review** when it has at least one of each group (`needs_review`): each
signal alone has honest explanations (students paste from their own editor; tiny problems
have few honest solutions), measured in docs/integrity.md.

`detect` sees only what the database has (`SubmissionInfo`): never the simulation's labels.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from codetutor.integrity.normalize import canonical, fingerprints, similarity

# Bumped when a signal or a default threshold changes, so stored flags say what made them.
INTEGRITY_VERSION = "1"  # thresholds chosen on seed 0 (2026-10-06, Step 2c)


class FlagKind(StrEnum):
    """One integrity signal (a value of `integrity_flags.kind`)."""

    PASTE = "paste"
    FAST_TYPING = "fast_typing"
    SAME_AS_STUDENT = "same_as_student"
    SAME_AS_AI = "same_as_ai"


ENTRY_KINDS = frozenset({FlagKind.PASTE, FlagKind.FAST_TYPING})
CONTENT_KINDS = frozenset({FlagKind.SAME_AS_STUDENT, FlagKind.SAME_AS_AI})


class IntegrityConfig(BaseModel):
    """Every threshold, in one place.

    The defaults were chosen on seed 0 on 2026-10-06 (best F0.5 of "needs review" over the grid
    in `integrity/evaluate.py`; paste 0.5, 0.7 and 0.9 tied, the tie rule takes the strictest)
    and are frozen as INTEGRITY_VERSION "1": changing one means a new version and a new report.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    paste_share: float = 0.9  # largest paste / code length
    chars_per_s: float = 5.0  # typed characters per active second
    typed_share: float = 0.8  # fast typing counts only if most of the code was typed
    similarity: float = 1.0  # token 4-gram Jaccard of the canonical code


@dataclass(frozen=True)
class SubmissionInfo:
    """What the checks may know about one submission: the database's view, no labels."""

    id: int
    student: str
    problem_id: str
    function_name: str
    created_at: datetime
    code: str
    editor_stats: Mapping[str, Any] | None  # None: no editor data (scripts, older rows)
    result_status: str | None  # None until graded


@dataclass(frozen=True)
class KnownAnswer:
    """An AI answer to a problem that the checks know (e.g. "ollama/qwen2.5-coder:7b#seed3")."""

    ref: str
    code: str


@dataclass(frozen=True)
class Flag:
    """One signal that fired on one submission, with a sentence a teacher can read."""

    submission_id: int
    kind: FlagKind
    value: float
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def detect(
    submissions: Sequence[SubmissionInfo],
    known_ai: Mapping[str, Sequence[KnownAnswer]],
    config: IntegrityConfig | None = None,
) -> list[Flag]:
    """Every signal that fires on `submissions`, sorted by submission id, then kind.

    `known_ai`: {problem id: known AI answers}. Deterministic: the same input gives the same
    flags in the same order.
    """
    config = config or IntegrityConfig()
    flags = entry_flags(submissions, config) + content_flags(submissions, known_ai, config)
    return sorted(flags, key=flag_order)


def flag_order(flag: Flag) -> tuple[int, int]:
    """The order `detect` returns flags in: by submission id, then in `FlagKind` order."""
    return flag.submission_id, list(FlagKind).index(flag.kind)


def needs_review(kinds: Iterable[FlagKind]) -> bool:
    """True when a submission has an entry signal and a content signal."""
    found = set(kinds)
    return bool(found & ENTRY_KINDS) and bool(found & CONTENT_KINDS)


# --- entry: paste and fast typing ---


def paste_share(submission: SubmissionInfo) -> float | None:
    """The largest paste as a share of the code's length (None without editor data)."""
    stats = submission.editor_stats
    if stats is None:
        return None
    return stats["largest_paste_chars"] / max(1, len(submission.code))


def typing_speed(submission: SubmissionInfo) -> float | None:
    """Typed characters per active second (None without editor data or active time)."""
    stats = submission.editor_stats
    if stats is None or stats["active_ms"] <= 0:
        return None
    return stats["typed_chars"] / (stats["active_ms"] / 1000)


def entry_flags(submissions: Sequence[SubmissionInfo], config: IntegrityConfig) -> list[Flag]:
    """The `paste` and `fast_typing` flags (the "how the code got in" half of `detect`)."""
    habits = _paste_habits(submissions, config)
    flags = []
    for submission in submissions:
        stats = submission.editor_stats
        share = paste_share(submission)
        if stats is None or share is None:
            continue
        if share >= config.paste_share:
            pasted, failing, total = habits[submission.student]
            flags.append(
                Flag(
                    submission.id,
                    FlagKind.PASTE,
                    share,
                    f"One paste of {stats['largest_paste_chars']} characters; the code has "
                    f"{len(submission.code)}. Context: this student pasted most of the code in "
                    f"{pasted} of {total} submissions ({failing} of those not accepted). "
                    "Students who write in their own editor do this honestly.",
                    {
                        "largest_paste_chars": stats["largest_paste_chars"],
                        "code_chars": len(submission.code),
                        "student_pasted": pasted,
                        "student_pasted_not_accepted": failing,
                        "student_submissions": total,
                    },
                )
            )
            continue
        speed = typing_speed(submission)
        typed = stats["typed_chars"]
        if (
            speed is not None
            and speed >= config.chars_per_s
            and typed >= config.typed_share * len(submission.code)
        ):
            flags.append(
                Flag(
                    submission.id,
                    FlagKind.FAST_TYPING,
                    speed,
                    f"{typed} characters typed in {stats['active_ms'] / 1000:.0f} s of activity "
                    f"({speed:.1f} per second, thinking time included), with no big paste.",
                    {"typed_chars": typed, "active_ms": stats["active_ms"]},
                )
            )
    return flags


def _paste_habits(
    submissions: Sequence[SubmissionInfo], config: IntegrityConfig
) -> dict[str, tuple[int, int, int]]:
    """{student: (submissions with a big paste, of those not accepted, submissions with editor
    data)}. Context for the teacher only: it never adds or removes a flag (decided 2026-10-06)."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for submission in submissions:
        share = paste_share(submission)
        if share is None:
            continue
        entry = counts[submission.student]
        entry[2] += 1
        if share >= config.paste_share:
            entry[0] += 1
            failed = submission.result_status not in (None, "accepted")
            entry[1] += failed
    return {student: (p, f, t) for student, (p, f, t) in counts.items()}


# --- content: the same structure as someone else's code ---


def content_flags(
    submissions: Sequence[SubmissionInfo],
    known_ai: Mapping[str, Sequence[KnownAnswer]],
    config: IntegrityConfig,
) -> list[Flag]:
    """The `same_as_student` and `same_as_ai` flags (the "what the code is" half of `detect`).

    A content flag's `value` is its best similarity, and it fires when that reaches
    `config.similarity`. So the flags for a higher threshold are exactly the flags whose value
    reaches it (only `details["students_matching"]` would count fewer students); the
    threshold search uses this to compare once instead of once per threshold.
    """
    prints = {s.id: _prints(s.code, s.function_name) for s in submissions}  # computed once
    flags = _same_as_student_flags(submissions, prints, config)
    return flags + _same_as_ai_flags(submissions, prints, known_ai, config)


def _same_as_student_flags(
    submissions: Sequence[SubmissionInfo],
    prints_by_id: Mapping[int, frozenset[tuple[str, ...]] | None],
    config: IntegrityConfig,
) -> list[Flag]:
    """Compare each submission with the earlier submissions of other students, same problem.

    Only the later submission is flagged: the earlier student may be the one copied from.
    """
    by_problem: dict[str, list[SubmissionInfo]] = defaultdict(list)
    for submission in submissions:
        by_problem[submission.problem_id].append(submission)
    flags = []
    for problem_id in sorted(by_problem):
        ordered = sorted(by_problem[problem_id], key=lambda s: (s.created_at, s.id))
        earlier: list[tuple[SubmissionInfo, frozenset[tuple[str, ...]]]] = []
        for submission in ordered:
            prints = prints_by_id[submission.id]
            if prints is None:
                continue
            matches = [
                (similarity(prints, other_prints), other)
                for other, other_prints in earlier
                if other.student != submission.student and other.created_at < submission.created_at
            ]
            close = [(score, other) for score, other in matches if score >= config.similarity]
            if close:
                # The closest match; among equals, the earliest (the likeliest original).
                score, other = min(close, key=lambda m: (-m[0], m[1].created_at, m[1].id))
                students = {o.student for _, o in close}
                gap_s = (submission.created_at - other.created_at).total_seconds()
                flags.append(
                    Flag(
                        submission.id,
                        FlagKind.SAME_AS_STUDENT,
                        score,
                        f"{_same(score)} {other.student}'s submission #{other.id}, "
                        f"{_duration(gap_s)} earlier (names and layout ignored). "
                        f"Earlier code of {len(students)} other student"
                        f"{'s' if len(students) != 1 else ''} matches this closely: "
                        "the more, the likelier an honest common solution.",
                        {
                            "matched_submission_id": other.id,
                            "matched_student": other.student,
                            "gap_s": gap_s,
                            "students_matching": len(students),
                        },
                    )
                )
            earlier.append((submission, prints))
    return flags


def _same_as_ai_flags(
    submissions: Sequence[SubmissionInfo],
    prints_by_id: Mapping[int, frozenset[tuple[str, ...]] | None],
    known_ai: Mapping[str, Sequence[KnownAnswer]],
    config: IntegrityConfig,
) -> list[Flag]:
    known_prints: dict[str, list[tuple[KnownAnswer, frozenset[tuple[str, ...]]]]] = {}
    flags = []
    for submission in submissions:
        if submission.problem_id not in known_prints:
            known_prints[submission.problem_id] = [
                (answer, prints)
                for answer in known_ai.get(submission.problem_id, [])
                if (prints := _prints(answer.code, submission.function_name)) is not None
            ]
        known = known_prints[submission.problem_id]
        prints = prints_by_id[submission.id]
        if prints is None or not known:
            continue
        # The closest known answer; among equals, the first in the list (a fixed order).
        score, answer = max(
            ((similarity(prints, p), a) for a, p in known), key=lambda m: m[0], default=(0.0, None)
        )
        if answer is not None and score >= config.similarity:
            flags.append(
                Flag(
                    submission.id,
                    FlagKind.SAME_AS_AI,
                    score,
                    f"{_same(score)} a known AI answer ({answer.ref}; names and layout "
                    f"ignored). Tiny problems have few solutions, so honest code can match too.",
                    {"ai_ref": answer.ref, "known_answers": len(known)},
                )
            )
    return flags


def _prints(code: str, function_name: str) -> frozenset[tuple[str, ...]] | None:
    text = canonical(code, function_name)
    return None if text is None else fingerprints(text)


def _same(score: float) -> str:
    return "Same structure as" if score == 1.0 else f"{score:.0%} the same structure as"


def _duration(seconds: float) -> str:
    """A rough duration for a sentence: "40 s", "12 min", "5 h", "3 days"."""
    if seconds < 60:
        return f"{seconds:.0f} s"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min"
    if seconds < 2 * 86400:
        return f"{seconds / 3600:.0f} h"
    return f"{seconds / 86400:.0f} days"
