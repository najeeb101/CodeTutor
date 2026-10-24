"""The pooled-draws report (Week 7 Step 2a). Fake runs, no GPU."""

from __future__ import annotations

import pytest

from codetutor.problems import Problem, load_all
from codetutor.rl.pooled import (
    draw_variance,
    pooled_difference_sd,
    pooled_rates,
    render_pooled_report,
)
from test_rl_baseline import _run


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    return load_all()


def _draws(bank: list[Problem], label: str, counts: tuple[int, ...]):  # type: ignore[no-untyped-def]
    """One fake run per draw: every problem passes `count` of its 10 answers."""
    return [_run(bank, f"{label} {k}", lambda p, i, c=c: i < c) for k, c in enumerate(counts)]


def test_pooling_three_draws_gives_thirty_answers_per_problem(bank: list[Problem]) -> None:
    draws = _draws(bank, "x", (3, 6, 9))
    ids = {p.id for p in bank}
    rates = pooled_rates(draws, ids)
    assert len(rates) == len(bank)
    assert all(r == pytest.approx(0.6) for r in rates.values())


def test_draw_variance_is_zero_for_identical_draws_and_grows_with_spread(
    bank: list[Problem],
) -> None:
    ids = {p.id for p in bank}
    assert draw_variance(_draws(bank, "x", (5, 5, 5)), ids) == 0
    # pass@1 0.4 / 0.5 / 0.6: sample variance 0.01 for every problem
    assert draw_variance(_draws(bank, "x", (4, 5, 6)), ids) == pytest.approx(0.01)


def test_difference_noise_shrinks_with_more_draws() -> None:
    # variance of one draw's pass@1 = 0.01; a difference of two models has 2 x that
    assert pooled_difference_sd(0.01, 1) == pytest.approx((0.02) ** 0.5)
    assert pooled_difference_sd(0.01, 3) == pytest.approx((0.02 / 3) ** 0.5)


def _report(bank: list[Problem], after_counts: tuple[int, ...]) -> str:
    base = _draws(bank, "before", (4, 5, 6))
    adapters = {n: _draws(bank, f"after {n}", after_counts) for n in ("a", "b", "c", "d")}
    return render_pooled_report(base, adapters, bank)


def test_a_big_gain_is_above_noise_and_no_gain_is_within(bank: list[Problem]) -> None:
    assert "above noise" in _report(bank, (8, 9, 9)).split("## 2.")[1]
    assert "within noise" in _report(bank, (4, 5, 6)).split("## 2.")[1]


def test_pooled_report_is_byte_identical_and_names_its_limits(bank: list[Problem]) -> None:
    report = _report(bank, (6, 7, 8))
    assert report == _report(bank, (6, 7, 8))
    assert "Training noise" in report
    assert "30 answers" in report
