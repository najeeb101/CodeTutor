"""Problem difficulty and student skill from first-attempt results (Week 5 Step 3).

The Rasch model: the chance that student s solves problem p on the first try is
`sigmoid(skill[s] - difficulty[p])`. Skill and difficulty live on one scale (logits); only
differences mean something, so difficulty is centred to mean 0 after the fit.

Pure Python, no labels, no database: it sees only (student, problem, solved) triples.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

PRIOR_SD = 1.0  # fixed by convention (a class's skills spread about 1 logit); never tuned
MAX_ITERATIONS = 200
TOLERANCE = 1e-6
SMOOTHING = 0.5  # pseudo-answers per side for the pass-rate baseline


@dataclass(frozen=True)
class Response:
    """One student's first try at one problem."""

    student: str
    problem: str
    solved: bool


@dataclass(frozen=True)
class RaschFit:
    """The fitted skills and difficulties, and whether the fit settled."""

    skill: dict[str, float]
    difficulty: dict[str, float]
    converged: bool
    iterations: int


def sigmoid(x: float) -> float:
    """1 / (1 + e^-x), without overflow for large |x|."""
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)


def fit_rasch(responses: Sequence[Response], prior_sd: float = PRIOR_SD) -> RaschFit:
    """Fit skills and difficulties by alternating Newton steps (a MAP estimate).

    A Gaussian prior (mean 0, spread `prior_sd`) on every skill and difficulty keeps a student
    who solved everything (or nothing) finite: without it their best skill is infinity.
    Deterministic: students and problems are visited in sorted order.
    """
    by_student: dict[str, list[tuple[str, float]]] = defaultdict(list)
    by_problem: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in responses:
        by_student[r.student].append((r.problem, float(r.solved)))
        by_problem[r.problem].append((r.student, float(r.solved)))
    skill = dict.fromkeys(sorted(by_student), 0.0)
    difficulty = dict.fromkeys(sorted(by_problem), 0.0)
    penalty = 1 / (prior_sd * prior_sd)
    converged = False
    iterations = 0
    while iterations < MAX_ITERATIONS and not converged:
        iterations += 1
        change = 0.0
        for s in skill:
            probs = [(sigmoid(skill[s] - difficulty[p]), y) for p, y in by_student[s]]
            gradient = sum(y - q for q, y in probs) - skill[s] * penalty
            curvature = sum(q * (1 - q) for q, _ in probs) + penalty
            step = gradient / curvature
            skill[s] += step
            change = max(change, abs(step))
        for p in difficulty:
            probs = [(sigmoid(skill[s] - difficulty[p]), y) for s, y in by_problem[p]]
            gradient = sum(q - y for q, y in probs) - difficulty[p] * penalty
            curvature = sum(q * (1 - q) for q, _ in probs) + penalty
            step = gradient / curvature
            difficulty[p] += step
            change = max(change, abs(step))
        converged = change < TOLERANCE
    shift = sum(difficulty.values()) / len(difficulty) if difficulty else 0.0
    return RaschFit(
        skill={s: v - shift for s, v in skill.items()},
        difficulty={p: v - shift for p, v in difficulty.items()},
        converged=converged,
        iterations=iterations,
    )


def logit_difficulty(solved: int, tried: int) -> float:
    """The simple baseline: how hard a problem looks from its pass rate, in logits.

    `log(failed / solved)` with half an answer added to each side, so a problem nobody (or
    everybody) solved stays finite. Higher = harder, like a Rasch difficulty.
    """
    return math.log((tried - solved + SMOOTHING) / (solved + SMOOTHING))


def pass_rate_baselines(
    responses: Sequence[Response],
) -> tuple[dict[str, float], dict[str, float]]:
    """(student skill, problem difficulty) from plain counts, no model.

    Skill = share of the student's problems solved; difficulty = `logit_difficulty`.
    """
    solved_by_student: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    solved_by_problem: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in responses:
        for counts in (solved_by_student[r.student], solved_by_problem[r.problem]):
            counts[0] += r.solved
            counts[1] += 1
    skill = {s: c[0] / c[1] for s, c in sorted(solved_by_student.items())}
    difficulty = {p: logit_difficulty(c[0], c[1]) for p, c in sorted(solved_by_problem.items())}
    return skill, difficulty
