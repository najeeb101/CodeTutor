"""The CPU benchmark's maths (Deploy Step 4): the same numbers the decision rule reads."""

from __future__ import annotations

import pytest

from codetutor.settings import tutor_model
from codetutor.tutor.cpu_bench import Row, choose_model, evenly_spaced, summarize


def _record(seconds: float, tokens: int, first_ok: bool, source: str = "model") -> dict:
    return {
        "latency_ms": seconds * 1000,
        "source": source,
        "first_attempt_ok": first_ok,
        "model_seconds": seconds if source != "reference" or tokens else 0.0,
        "completion_tokens": tokens,
    }


def test_summary_numbers() -> None:
    records = [
        _record(10, 100, True),
        _record(20, 100, False),
        _record(30, 100, True),
        _record(40, 100, False, "reference"),
    ]
    row = summarize("m", records)

    assert row.hints == 4
    assert row.median_s == 25.0
    assert row.p90_s == 40.0
    assert row.tokens_per_s == pytest.approx(400 / 100)
    assert row.first_blocked_share == 0.5
    assert row.reference_share == 0.25


def test_an_empty_run_is_refused() -> None:
    with pytest.raises(ValueError, match="no hints"):
        summarize("m", [])


def test_evenly_spaced_picks_a_spread_and_never_more_than_there_is() -> None:
    assert evenly_spaced(list(range(100)), 4) == [0, 25, 50, 75]
    assert evenly_spaced([1, 2, 3], 12) == [1, 2, 3]
    assert evenly_spaced([], 5) == []


def _row(name: str, median_s: float, reference_share: float) -> Row:
    return Row(name, 12, median_s, median_s * 1.5, 5.0, 0.3, reference_share)


def test_the_rule_picks_the_largest_model_that_passes_both_limits() -> None:
    rows = [_row("1.5b", 5, 0.1), _row("3b", 12, 0.2), _row("7b", 45, 0.05)]
    assert (
        choose_model(rows, order=["1.5b", "3b", "7b"], max_median_s=20, max_reference=0.3) == "3b"
    )


def test_a_model_over_either_limit_is_skipped() -> None:
    rows = [_row("1.5b", 5, 0.1), _row("3b", 12, 0.5), _row("7b", 15, 0.1)]
    assert (
        choose_model(rows, order=["1.5b", "3b", "7b"], max_median_s=20, max_reference=0.3) == "7b"
    )
    slow = [_row("1.5b", 5, 0.1), _row("3b", 12, 0.5), _row("7b", 45, 0.1)]
    assert (
        choose_model(slow, order=["1.5b", "3b", "7b"], max_median_s=20, max_reference=0.3) == "1.5b"
    )


def test_if_none_passes_the_smallest_is_chosen() -> None:
    rows = [_row("1.5b", 30, 0.6), _row("3b", 40, 0.6)]
    assert choose_model(rows, order=["1.5b", "3b"], max_median_s=20, max_reference=0.3) == "1.5b"


def test_the_tutor_model_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TUTOR_MODEL", raising=False)
    assert tutor_model().startswith("ollama/")
    monkeypatch.setenv("TUTOR_MODEL", "ollama/qwen2.5-coder:1.5b")
    assert tutor_model() == "ollama/qwen2.5-coder:1.5b"
    monkeypatch.setenv("TUTOR_MODEL", "")
    assert tutor_model().startswith("ollama/")
