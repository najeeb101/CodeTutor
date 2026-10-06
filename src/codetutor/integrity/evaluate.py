"""How good are the integrity checks? Precision, recall and F0.5 against the simulation's labels
(Week 5 Step 2c, docs/integrity.md §2.4).

The only integrity module that reads labels: the checks themselves (`signals.py`) see the
database's view only. Thresholds are chosen on seed 0 (`search`) and reported on held-out
seed 1 (`report.py`), with 95% intervals that resample **students**, not rows: one student's
rows are not independent (a copier makes many similar ones).
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import product

from codetutor.integrity.signals import (
    Flag,
    FlagKind,
    IntegrityConfig,
    KnownAnswer,
    SubmissionInfo,
    content_flags,
    entry_flags,
    flag_order,
    needs_review,
)
from codetutor.sim.cohort import CohortRow, Label

BETA = 0.5  # precision counts more than recall: a false flag costs an honest student's time
GRID_PASTE_SHARE = (0.3, 0.5, 0.7, 0.9)
GRID_CHARS_PER_S = (3.0, 4.0, 5.0, 6.0, 7.0)
GRID_SIMILARITY = (0.8, 0.9, 1.0)
ROUNDS = 2000  # bootstrap resamples
SEED = 0  # bootstrap seed (fixed: the report is byte-identical on every run)


class LabelMismatchError(ValueError):
    """The database's submissions and the cohort file don't describe the same class."""


@dataclass(frozen=True)
class Labelled:
    """A submission as the checks see it, with its true label (for scoring only)."""

    submission: SubmissionInfo
    label: Label


def labelled(submissions: Sequence[SubmissionInfo], rows: Sequence[CohortRow]) -> list[Labelled]:
    """Join each submission with its cohort row by (student, problem, time), unique by
    construction (like `sim.load.graded_rows`). Every submission and every row must match."""
    by_key: dict[tuple[str, str, datetime], CohortRow] = {
        (row.student, row.problem_id, row.created_at): row for row in rows
    }
    if len(by_key) != len(rows) or len(submissions) != len(rows):
        raise LabelMismatchError(
            f"{len(submissions)} submissions vs {len(rows)} cohort rows "
            f"({len(by_key)} distinct keys): is this the right database for this cohort file?"
        )
    joined = []
    for submission in submissions:
        key = (submission.student, submission.problem_id, submission.created_at)
        if key not in by_key:
            raise LabelMismatchError(f"submission #{submission.id} {key} has no cohort row")
        joined.append(Labelled(submission, by_key[key].label))
    return joined


def f_beta(precision: float, recall: float, beta: float = BETA) -> float:
    """The weighted harmonic mean of precision and recall; 0.0 when both are 0.

    F_beta = (1 + beta²)·P·R / (beta²·P + R). beta = 1 is the usual F1; beta = 0.5 treats
    recall as half as important as precision, so a setting that flags fewer honest students
    wins unless it misses many more cheaters.
    """
    weight = beta * beta
    denominator = weight * precision + recall
    if denominator == 0:
        return 0.0
    return (1 + weight) * precision * recall / denominator


@dataclass(frozen=True)
class Scores:
    """How one set of flagged submissions compares with the labels."""

    flagged: int
    true_positives: int
    positives: int  # cheating submissions in the class

    @property
    def precision(self) -> float | None:
        """Share of flagged submissions that are cheating (None when nothing is flagged)."""
        return self.true_positives / self.flagged if self.flagged else None

    @property
    def recall(self) -> float | None:
        """Share of cheating submissions that are flagged (None when there are none)."""
        return self.true_positives / self.positives if self.positives else None

    @property
    def f(self) -> float:
        """F0.5 (an undefined precision or recall counts as 0)."""
        return f_beta(self.precision or 0.0, self.recall or 0.0)


def score(flagged: Iterable[int], rows: Sequence[Labelled]) -> Scores:
    """Score the flagged submission ids against the labels of `rows`."""
    cheating = {r.submission.id for r in rows if r.label.cheating}
    found = set(flagged) & {r.submission.id for r in rows}
    return Scores(len(found), len(found & cheating), len(cheating))


def review_ids(flags: Iterable[Flag]) -> set[int]:
    """The submissions that need review (an entry and a content signal)."""
    return {sid for sid, kinds in kinds_by_submission(flags).items() if needs_review(kinds)}


def signal_ids(flags: Iterable[Flag], kind: FlagKind) -> set[int]:
    """The submissions on which one signal fired."""
    return {flag.submission_id for flag in flags if flag.kind == kind}


def kinds_by_submission(flags: Iterable[Flag]) -> dict[int, set[FlagKind]]:
    """{submission id: the signals that fired on it}."""
    kinds: dict[int, set[FlagKind]] = defaultdict(set)
    for flag in flags:
        kinds[flag.submission_id].add(flag.kind)
    return kinds


# --- the threshold search (seed 0 only) ---


class FastFlags:
    """The flags of `detect` for many settings, comparing the code only once.

    Content flags are computed at the lowest similarity; for a higher threshold the flags
    whose value reaches it are exactly the ones `detect` would give (see `content_flags`).
    A test checks this against `detect` at every grid point.
    """

    def __init__(
        self,
        submissions: Sequence[SubmissionInfo],
        known_ai: Mapping[str, Sequence[KnownAnswer]],
        lowest_similarity: float = min(GRID_SIMILARITY),
    ) -> None:
        self.submissions = submissions
        self.lowest_similarity = lowest_similarity
        config = IntegrityConfig(similarity=lowest_similarity)
        self._content = content_flags(submissions, known_ai, config)

    def flags(self, config: IntegrityConfig) -> list[Flag]:
        """Every flag `detect(submissions, known_ai, config)` gives, in the same order."""
        if config.similarity < self.lowest_similarity:
            raise ValueError(
                f"similarity {config.similarity} is below the precomputed {self.lowest_similarity}"
            )
        content = [f for f in self._content if f.value >= config.similarity]
        return sorted(entry_flags(self.submissions, config) + content, key=flag_order)


@dataclass(frozen=True)
class GridPoint:
    """One setting of the grid and how "needs review" scores with it."""

    config: IntegrityConfig
    scores: Scores


def grid_configs(base: IntegrityConfig | None = None) -> list[IntegrityConfig]:
    """The 60 settings searched: paste share × typing speed × similarity (others from `base`)."""
    base = base or IntegrityConfig()
    return [
        base.model_copy(update={"paste_share": p, "chars_per_s": c, "similarity": s})
        for p, c, s in product(GRID_PASTE_SHARE, GRID_CHARS_PER_S, GRID_SIMILARITY)
    ]


def search(fast: FastFlags, rows: Sequence[Labelled]) -> list[GridPoint]:
    """Every grid setting, best first.

    Best = highest F0.5 of "needs review". Ties go to the stricter setting: fewer flagged
    submissions first, then higher thresholds (paste share, then speed, then similarity).
    """
    points = [GridPoint(c, score(review_ids(fast.flags(c)), rows)) for c in grid_configs()]
    return sorted(points, key=_rank)


def _rank(point: GridPoint) -> tuple[float, int, float, float, float]:
    config = point.config
    return (
        -point.scores.f,
        point.scores.flagged,
        -config.paste_share,
        -config.chars_per_s,
        -config.similarity,
    )


# --- intervals over students ---


@dataclass(frozen=True)
class Interval:
    """A 95% bootstrap interval; `undefined` resamples had no value (e.g. nothing flagged)."""

    low: float
    high: float
    undefined: int


def student_intervals(
    flagged: Iterable[int], rows: Sequence[Labelled], rounds: int = ROUNDS, seed: int = SEED
) -> tuple[Interval | None, Interval | None]:
    """95% intervals for (precision, recall), resampling students with replacement.

    Each resample draws as many students as the class has (a student can be drawn twice),
    pools their submissions and recomputes precision and recall. Deterministic for the same
    rows and seed (students are taken in name order).
    """
    flagged_ids = set(flagged)
    per_student: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        counts = per_student[row.submission.student]
        is_flagged = row.submission.id in flagged_ids
        counts[0] += is_flagged
        counts[1] += is_flagged and row.label.cheating
        counts[2] += row.label.cheating
    students = [per_student[name] for name in sorted(per_student)]
    if not students:
        return None, None
    rng = random.Random(seed)
    precisions: list[float] = []
    recalls: list[float] = []
    for _ in range(rounds):
        drawn = rng.choices(students, k=len(students))
        n_flagged = sum(c[0] for c in drawn)
        n_true = sum(c[1] for c in drawn)
        n_cheating = sum(c[2] for c in drawn)
        if n_flagged:
            precisions.append(n_true / n_flagged)
        if n_cheating:
            recalls.append(n_true / n_cheating)
    return _interval(precisions, rounds), _interval(recalls, rounds)


def _interval(values: list[float], rounds: int) -> Interval | None:
    """The 2.5% and 97.5% points, as in `evals.metrics.bootstrap_mean_ci`."""
    if not values:
        return None
    values = sorted(values)
    n = len(values)
    return Interval(values[int(0.025 * n)], values[int(0.975 * n) - 1], rounds - n)


# --- where the checks succeed and fail ---


def case_of(label: Label) -> str:
    """A short name for how a row was made, e.g. "copy, renamed" or "honest, ide_paste"."""
    if not label.cheating:
        return f"honest, {label.entry.value}"
    return f"{label.source_kind.value} {label.transform.value}, {label.entry.value}"


def caught_by_case(flagged: Iterable[int], rows: Sequence[Labelled]) -> dict[str, tuple[int, int]]:
    """{case: (flagged, total)} over every row, cheating and honest."""
    flagged_ids = set(flagged)
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for row in rows:
        case = case_of(row.label)
        totals[case] += 1
        hits[case] += row.submission.id in flagged_ids
    return {case: (hits[case], totals[case]) for case in sorted(totals)}


def false_flag_signals(flags: Sequence[Flag], rows: Sequence[Labelled]) -> dict[str, int]:
    """{"paste + same_as_student": count, ...} over honest submissions that need review."""
    kinds = kinds_by_submission(flags)
    honest = {r.submission.id for r in rows if not r.label.cheating}
    combos: Counter[str] = Counter()
    for sid in review_ids(flags) & honest:
        combos[" + ".join(k.value for k in FlagKind if k in kinds[sid])] += 1
    return dict(sorted(combos.items(), key=lambda item: (-item[1], item[0])))


@dataclass(frozen=True)
class StudentView:
    """What a teacher would see per student: who has at least one submission to review."""

    cheating_students: int  # students with at least one cheating submission
    cheating_students_flagged: int
    honest_students: int
    honest_students_flagged: int  # honest students with at least one false flag


def student_view(flagged: Iterable[int], rows: Sequence[Labelled]) -> StudentView:
    """Count students, not rows: a teacher reviews a student's flagged submissions together."""
    flagged_ids = set(flagged)
    cheats: set[str] = set()
    any_flag: set[str] = set()
    false_flag: set[str] = set()
    for row in rows:
        student = row.submission.student
        if row.label.cheating:
            cheats.add(student)
        if row.submission.id in flagged_ids:
            any_flag.add(student)
            if not row.label.cheating:
                false_flag.add(student)
    everyone = {row.submission.student for row in rows}
    honest = everyone - cheats
    return StudentView(len(cheats), len(cheats & any_flag), len(honest), len(honest & false_flag))
