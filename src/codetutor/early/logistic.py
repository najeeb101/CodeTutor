"""Logistic regression in pure Python (Week 8 Step 3a): Newton steps, a fixed L2 penalty.

P(at risk) = sigmoid(bias + sum(weight_j * z_j)), where z is the feature standardised with the
training mean and spread. The penalty keeps the weights finite when the classes separate
perfectly (small classes do that). It is fixed, never tuned. Deterministic: no randomness.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from codetutor.skill.rasch import sigmoid

L2 = 1.0
MAX_ITERATIONS = 50
TOLERANCE = 1e-8


@dataclass(frozen=True)
class LogisticModel:
    """Weights on standardised features, plus what is needed to standardise a new row."""

    means: list[float]
    spreads: list[float]
    weights: list[float]
    bias: float
    iterations: int


def solve(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Solve matrix · x = rhs by Gaussian elimination with partial pivoting."""
    n = len(rhs)
    rows = [[*matrix[i], rhs[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        if abs(rows[col][col]) < 1e-12:
            raise ValueError("the system has no unique solution")
        for r in range(col + 1, n):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, n + 1):
                rows[r][c] -= factor * rows[col][c]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (rows[i][n] - sum(rows[i][j] * x[j] for j in range(i + 1, n))) / rows[i][i]
    return x


def standardise(
    x: Sequence[Sequence[float]],
) -> tuple[list[float], list[float]]:
    """Mean and spread per column; a constant column gets spread 1 (it becomes all zeros)."""
    n = len(x)
    means = [sum(row[j] for row in x) / n for j in range(len(x[0]))]
    spreads = []
    for j, m in enumerate(means):
        sd = math.sqrt(sum((row[j] - m) ** 2 for row in x) / n)
        spreads.append(sd if sd > 1e-12 else 1.0)
    return means, spreads


def fit_logistic(x: Sequence[Sequence[float]], y: Sequence[bool], l2: float = L2) -> LogisticModel:
    """Fit by Newton's method. `x`: one row per student; `y`: True = at risk."""
    if not x or len(x) != len(y):
        raise ValueError("need the same, non-zero number of rows and labels")
    means, spreads = standardise(x)
    z = [[(v - m) / s for v, m, s in zip(row, means, spreads, strict=True)] for row in x]
    dim = len(means)
    beta = [0.0] * (dim + 1)  # beta[0] is the bias; it is not penalised
    iterations = 0
    while iterations < MAX_ITERATIONS:
        iterations += 1
        grad = [0.0] * (dim + 1)
        hess = [[0.0] * (dim + 1) for _ in range(dim + 1)]
        for row, label in zip(z, y, strict=True):
            full = [1.0, *row]
            p = sigmoid(sum(b * v for b, v in zip(beta, full, strict=True)))
            for i in range(dim + 1):
                grad[i] += (float(label) - p) * full[i]
                for j in range(dim + 1):
                    hess[i][j] += p * (1 - p) * full[i] * full[j]
        for i in range(1, dim + 1):
            grad[i] -= l2 * beta[i]
            hess[i][i] += l2
        step = solve(hess, grad)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < TOLERANCE:
            break
    return LogisticModel(means, spreads, beta[1:], beta[0], iterations)


def predict(model: LogisticModel, row: Sequence[float]) -> float:
    """The model's probability that this student is at risk."""
    z = sum(
        w * (v - m) / s
        for w, v, m, s in zip(model.weights, row, model.means, model.spreads, strict=True)
    )
    return sigmoid(model.bias + z)
