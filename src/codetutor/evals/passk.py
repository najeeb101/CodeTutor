"""pass@k: the chance that at least one of k attempts solves a problem.

We draw n samples for a problem and c of them pass. The unbiased estimator (Chen et al. 2021,
"Evaluating Large Language Models Trained on Code") is

    pass@k = 1 - C(n - c, k) / C(n, k)

C(n, k) counts the ways to pick k of the n samples; C(n - c, k) counts the ways to pick k that
all fail. So the fraction is "the chance that k samples picked at random all fail".
"""

from __future__ import annotations


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k for one problem with `n` samples, of which `c` passed.

    Raises ValueError unless 0 <= c <= n and 1 <= k <= n.
    """
    if not 0 <= c <= n:
        raise ValueError(f"need 0 <= c <= n, got c={c}, n={n}")
    if not 1 <= k <= n:
        raise ValueError(f"need 1 <= k <= n, got k={k}, n={n}")
    if n - c < k:
        return 1.0  # fewer than k failing samples: every pick of k contains a passing one
    # C(n - c, k) / C(n, k) is the product of (1 - k / i) for i = n - c + 1 .. n. Each factor is
    # between 0 and 1, so there are no huge factorials and no overflow (the Codex paper's trick).
    all_fail = 1.0
    for i in range(n - c + 1, n + 1):
        all_fail *= 1.0 - k / i
    return 1.0 - all_fail
