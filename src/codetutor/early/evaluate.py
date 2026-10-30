"""Labels, scores and the experiment (Week 8 Step 3a).

The question: at the end of week `cutoff`, who will solve fewer than `AT_RISK_BELOW` of the
problems they first try *after* the cutoff, on the first try? The label is read from the
submissions table (outcomes), never from the simulator's persona labels.
Fit on one class, score another class (seed 0 -> seed 1), as in Week 5.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from codetutor.early.features import FEATURE_NAMES, features_at, week_of
from codetutor.early.logistic import LogisticModel, fit_logistic, predict
from codetutor.integrity.signals import SubmissionInfo

AT_RISK_BELOW = 0.4  # fixed before looking at any result; not tuned
MAIN_CUTOFF = 3
TOP_K = 10  # how many students a teacher looks at; no probability threshold to tune
ROUNDS = 2000
SEED = 0


def labels(submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime) -> dict[str, bool]:
    """True = at risk. A student is labelled only if they have a graded first try after the
    cutoff: the share of those first tries that were accepted is below `AT_RISK_BELOW`."""
    first: dict[tuple[str, str], SubmissionInfo] = {}
    for s in sorted(submissions, key=lambda s: (s.created_at, s.id)):
        first.setdefault((s.student, s.problem_id), s)
    later: dict[str, list[bool]] = {}
    for (student, _), s in first.items():
        if week_of(s.created_at, start) > cutoff and s.result_status is not None:
            later.setdefault(student, []).append(s.result_status == "accepted")
    return {name: sum(v) / len(v) < AT_RISK_BELOW for name, v in sorted(later.items())}


def auc(scores: Sequence[float], at_risk: Sequence[bool]) -> float:
    """The chance that a random at-risk student scores higher than a random other student
    (a tie counts half). 0.5 = no better than chance; 1.0 = a perfect ordering.

    Compares every at-risk/other pair, which is fine for a class of 60.
    """
    positives = [s for s, y in zip(scores, at_risk, strict=True) if y]
    negatives = [s for s, y in zip(scores, at_risk, strict=True) if not y]
    if not positives or not negatives:
        raise ValueError("AUC needs at least one at-risk and one other student")
    wins = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives)
    return wins / (len(positives) * len(negatives))


def top_k(scores: Mapping[str, float], at_risk: Mapping[str, bool], k: int) -> list[str]:
    """The k highest-scoring students (ties by name, so the result is deterministic)."""
    return sorted(scores, key=lambda name: (-scores[name], name))[:k]


def precision_recall(flagged: Sequence[str], at_risk: Mapping[str, bool]) -> tuple[float, float]:
    """Of the flagged students how many are at risk; of the at-risk students how many flagged."""
    hits = sum(at_risk[name] for name in flagged)
    positives = sum(at_risk.values())
    return hits / len(flagged), hits / positives


def bootstrap_auc(
    scores: Sequence[float], at_risk: Sequence[bool], rounds: int = ROUNDS, seed: int = SEED
) -> tuple[float, float]:
    """A 95% interval for AUC, resampling students. Resamples that miss a class are skipped."""
    pairs = list(zip(scores, at_risk, strict=True))
    rng = random.Random(seed)
    values = []
    for _ in range(rounds):
        drawn = rng.choices(pairs, k=len(pairs))
        if any(y for _, y in drawn) and not all(y for _, y in drawn):
            values.append(auc([s for s, _ in drawn], [y for _, y in drawn]))
    values.sort()
    return values[int(0.025 * len(values))], values[int(0.975 * len(values)) - 1]


@dataclass(frozen=True)
class MethodScore:
    name: str
    auc: float
    low: float
    high: float
    precision: float  # of the TOP_K flagged
    recall: float


@dataclass(frozen=True)
class Experiment:
    """One cutoff, one class scored."""

    cutoff: int
    scored: int  # students with features and a label
    positives: int
    no_label: int  # active by the cutoff, no graded first try after it
    not_started: int  # a label but no submission by the cutoff
    base_rate: float
    methods: list[MethodScore]
    flagged: list[str]  # the model's top TOP_K


def training_data(
    submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime
) -> tuple[list[str], list[list[float]], list[bool]]:
    """Students with both features and a label: names, feature rows, labels."""
    x = features_at(submissions, cutoff, start)
    y = labels(submissions, cutoff, start)
    names = sorted(set(x) & set(y))
    return names, [x[n] for n in names], [y[n] for n in names]


def fit_for(submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime) -> LogisticModel:
    """Fit the model on one class."""
    _, rows, y = training_data(submissions, cutoff, start)
    return fit_logistic(rows, y)


def score_class(
    model: LogisticModel, submissions: Sequence[SubmissionInfo], cutoff: int, start: datetime
) -> Experiment:
    """Score a class with a fitted model and with the two simple baselines."""
    names, rows, y = training_data(submissions, cutoff, start)
    at_risk = dict(zip(names, y, strict=True))
    column = {name: i for i, name in enumerate(FEATURE_NAMES)}
    ways: dict[str, dict[str, float]] = {
        "Logistic model": {n: predict(model, r) for n, r in zip(names, rows, strict=True)},
        "Low first-try share": {
            n: 1 - r[column["first_try_share"]] for n, r in zip(names, rows, strict=True)
        },
        "Days since last submission": {
            n: r[column["days_since_last"]] for n, r in zip(names, rows, strict=True)
        },
    }
    methods = []
    for name, scores in ways.items():
        values = [scores[n] for n in names]
        low, high = bootstrap_auc(values, y)
        precision, recall = precision_recall(top_k(scores, at_risk, TOP_K), at_risk)
        methods.append(MethodScore(name, auc(values, y), low, high, precision, recall))
    all_features = features_at(submissions, cutoff, start)
    all_labels = labels(submissions, cutoff, start)
    return Experiment(
        cutoff=cutoff,
        scored=len(names),
        positives=sum(y),
        no_label=len(set(all_features) - set(all_labels)),
        not_started=len(set(all_labels) - set(all_features)),
        base_rate=sum(y) / len(y),
        methods=methods,
        flagged=top_k(ways["Logistic model"], at_risk, TOP_K),
    )


def stoppers(submissions: Sequence[SubmissionInfo], start: datetime) -> set[str]:
    """Students whose last submission is before the class's last week (they stopped coming)."""
    last_week = max(week_of(s.created_at, start) for s in submissions)
    latest: dict[str, int] = {}
    for s in submissions:
        latest[s.student] = max(latest.get(s.student, 0), week_of(s.created_at, start))
    return {name for name, week in latest.items() if week < last_week}
