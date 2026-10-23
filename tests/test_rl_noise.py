"""The eval-noise report (Week 7 Step 1). Fake runs, no GPU."""

from __future__ import annotations

import pytest

from codetutor.problems import Problem, load_all
from codetutor.rl.after import FoldRun
from codetutor.rl.noise import noise_half_width, reeval_differences, render_noise_report, spread
from test_rl_baseline import _run


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    return load_all()


def _jitter(bank: list[Problem], base: int, shift: int):  # type: ignore[no-untyped-def]
    """pass@1 ~ base/10, plus or minus one answer, differently for each draw."""
    index = {p.id: k for k, p in enumerate(bank)}

    def ok(problem: Problem, i: int) -> bool:
        return i < base + (1 if (index[problem.id] + shift) % 2 else 0)

    return ok


def test_reeval_differences_are_second_minus_first(bank: list[Problem]) -> None:
    first = _run(bank, "a", lambda p, i: i < 3)
    second = _run(bank, "b", lambda p, i: i < 5)
    diffs = reeval_differences(first, second)
    assert len(diffs) == len(bank)
    assert all(d == pytest.approx(0.2) for d in diffs.values())


def test_spread_and_band() -> None:
    assert spread([0.1]) is None
    assert spread([0.1, -0.1]) == pytest.approx(0.1414, abs=1e-3)
    assert noise_half_width(0.1, 4) == pytest.approx(1.96 * 0.1 / 2)


def _report(bank: list[Problem], after_base: int) -> str:
    b0 = _run(bank, "before", _jitter(bank, 5, 0))
    b1 = _run(bank, "before'", _jitter(bank, 5, 1))
    a0 = _run(bank, "after", _jitter(bank, after_base, 0))
    a1 = _run(bank, "after'", _jitter(bank, after_base, 1))
    folds = {"c": (FoldRun("c", "c", 0, b0, a0), FoldRun("c", "c", 0, b1, a1))}
    return render_noise_report((b0, b1), {"c": (a0, a1)}, folds, bank)


def test_a_big_gain_is_above_noise_and_no_gain_is_within(bank: list[Problem]) -> None:
    assert "above noise" in _report(bank, after_base=9).split("## 2.")[1]
    assert "within noise" in _report(bank, after_base=5).split("## 2.")[1]


def test_noise_report_is_byte_identical_and_names_its_limit(bank: list[Problem]) -> None:
    report = _report(bank, after_base=7)
    assert report == _report(bank, after_base=7)
    assert "Training noise" in report or "**Training noise**" in report
