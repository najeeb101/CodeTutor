"""How close are the estimates to the simulated truth? (Week 5 Step 3, docs/integrity.md §3)

The only skill module that reads truth (the cohort file's true skill and difficulty). The
estimates themselves (`rasch.py`) never see it, except through the evaluation's own
"missing data" experiments, which use the truth to decide who skips what.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean

from codetutor.skill.rasch import Response, fit_rasch, pass_rate_baselines, sigmoid

ROUNDS = 2000  # bootstrap resamples
SEED = 0  # fixed: the report is byte-identical on every run
REPEATS = 20  # random deletions per missing-data experiment
DROP_RANDOM = 0.3  # share of responses deleted at random
DROP_SKIP = 0.6  # chance a response is deleted when the problem is certainly too hard


@dataclass(frozen=True)
class Agreement:
    """How an estimate relates to the truth. Both are on a scale whose zero is arbitrary."""

    pearson: float
    spearman: float
    rmse: float  # after moving both to mean 0
    n: int


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson correlation; 0.0 when either side is constant."""
    mx, my = mean(x), mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / math.sqrt(sxx * syy)


def ranks(values: Sequence[float]) -> list[float]:
    """Ranks starting at 1; equal values share the average of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def compare(estimate: Mapping[str, float], truth: Mapping[str, float]) -> Agreement:
    """Agreement over the names both sides have, in sorted-name order.

    RMSE is computed after centring both to mean 0, because the zero point of the scale is
    arbitrary. For a pass-rate baseline (another unit than logits) only the correlations mean
    something.
    """
    names = sorted(set(estimate) & set(truth))
    x = [estimate[n] for n in names]
    y = [truth[n] for n in names]
    mx, my = mean(x), mean(y)
    rmse = math.sqrt(mean(((a - mx) - (b - my)) ** 2 for a, b in zip(x, y, strict=True)))
    return Agreement(pearson(x, y), pearson(ranks(x), ranks(y)), rmse, len(names))


def bootstrap_pearson(
    estimate: Mapping[str, float],
    truth: Mapping[str, float],
    rounds: int = ROUNDS,
    seed: int = SEED,
) -> tuple[float, float]:
    """A 95% interval for Pearson r, resampling the **units** (students or problems) with
    replacement. It shows how much r depends on which units we had; it does not include the
    noise in each unit's estimate. Resamples where one side is constant count as r = 0."""
    names = sorted(set(estimate) & set(truth))
    pairs = [(estimate[n], truth[n]) for n in names]
    rng = random.Random(seed)
    values = []
    for _ in range(rounds):
        drawn = rng.choices(pairs, k=len(pairs))
        values.append(pearson([a for a, _ in drawn], [b for _, b in drawn]))
    values.sort()
    return values[int(0.025 * rounds)], values[int(0.975 * rounds) - 1]


@dataclass(frozen=True)
class Estimates:
    """Both methods on one set of responses."""

    rasch_skill: dict[str, float]
    rasch_difficulty: dict[str, float]
    rate_skill: dict[str, float]
    rate_difficulty: dict[str, float]
    converged: bool
    iterations: int


def estimate(responses: Sequence[Response]) -> Estimates:
    """Rasch and the pass-rate baselines on the same responses."""
    fit = fit_rasch(responses)
    rate_skill, rate_difficulty = pass_rate_baselines(responses)
    return Estimates(
        fit.skill, fit.difficulty, rate_skill, rate_difficulty, fit.converged, fit.iterations
    )


def drop_random(responses: Sequence[Response], rng: random.Random) -> list[Response]:
    """Delete `DROP_RANDOM` of the responses at random (data missing by accident)."""
    return [r for r in responses if rng.random() >= DROP_RANDOM]


def drop_skipped(
    responses: Sequence[Response],
    skill: Mapping[str, float],
    difficulty: Mapping[str, float],
    rng: random.Random,
) -> list[Response]:
    """Delete responses more often when the problem is too hard for the student (data missing
    because students skip what they expect to fail). Uses the TRUE skill and difficulty to
    decide: this builds the missing-data situation; the estimates never see them."""
    kept = []
    for r in responses:
        chance_to_solve = sigmoid(skill[r.student] - difficulty[r.problem])
        if rng.random() >= DROP_SKIP * (1 - chance_to_solve):
            kept.append(r)
    return kept


@dataclass(frozen=True)
class MissingResult:
    """Mean Pearson r over `REPEATS` seeded deletions, for each method."""

    kept: float  # mean share of responses left
    rasch_difficulty: float
    rate_difficulty: float
    rasch_skill: float
    rate_skill: float


def missing_data_experiment(
    responses: Sequence[Response],
    true_skill: Mapping[str, float],
    true_difficulty: Mapping[str, float],
    how: str,
    seed: int = SEED,
) -> MissingResult:
    """Delete responses (`how` = "random" or "skip") `REPEATS` times and refit both methods."""
    rng = random.Random(seed)
    kept_share: list[float] = []
    scores: dict[str, list[float]] = defaultdict(list)
    for _ in range(REPEATS):
        if how == "random":
            left = drop_random(responses, rng)
        elif how == "skip":
            left = drop_skipped(responses, true_skill, true_difficulty, rng)
        else:
            raise ValueError(f"unknown deletion {how!r}")
        kept_share.append(len(left) / len(responses))
        e = estimate(left)
        scores["rd"].append(compare(e.rasch_difficulty, true_difficulty).pearson)
        scores["pd"].append(compare(e.rate_difficulty, true_difficulty).pearson)
        scores["rs"].append(compare(e.rasch_skill, true_skill).pearson)
        scores["ps"].append(compare(e.rate_skill, true_skill).pearson)
    return MissingResult(
        mean(kept_share),
        mean(scores["rd"]),
        mean(scores["pd"]),
        mean(scores["rs"]),
        mean(scores["ps"]),
    )


@dataclass(frozen=True)
class DeclaredCheck:
    """One problem: its declared level against the estimated difficulty."""

    problem: str
    declared: str
    estimated: float
    level_mean: float  # mean estimated difficulty of problems with the same declared level

    @property
    def gap(self) -> float:
        """How far above (+) or below (-) its level's average this problem is."""
        return self.estimated - self.level_mean


def declared_vs_estimated(
    difficulty: Mapping[str, float], declared: Mapping[str, str]
) -> list[DeclaredCheck]:
    """Every problem with its declared level, biggest disagreement (|gap|) first."""
    levels: dict[str, list[float]] = defaultdict(list)
    for problem, value in difficulty.items():
        levels[declared[problem]].append(value)
    checks = [
        DeclaredCheck(p, declared[p], v, mean(levels[declared[p]])) for p, v in difficulty.items()
    ]
    return sorted(checks, key=lambda c: (-abs(c.gap), c.problem))
