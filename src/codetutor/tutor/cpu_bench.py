"""The tutor on a CPU (Deploy Step 4): measure each candidate model, then apply a rule.

The server has no GPU, so the hint model runs on the CPU. How big a model that can be is a
measurement, not a guess: for the same buggy-code situations we time the real `give_hint`
pipeline and count how often the guardrail made the tutor fall back to the teacher's hint.
The rule that picks the model is written here, before any run (docs/tutor.md §6).
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from codetutor.tutor.service import HintResult

T = TypeVar("T")

# The rule (docs/tutor.md §6): the LARGEST model whose median hint takes at most this many
# seconds and which falls back to the teacher's hint in at most this share of hints.
MAX_MEDIAN_S = 20.0
MAX_REFERENCE_SHARE = 0.30


@dataclass(frozen=True)
class Row:
    """One model's numbers over the benchmark's hints."""

    model: str
    hints: int
    median_s: float  # seconds from request to the hint shown, retries included
    p90_s: float
    tokens_per_s: float  # generated tokens per second of model time
    first_blocked_share: float  # first reply blocked by the guardrail (or empty / too long)
    reference_share: float  # the teacher's reference hint was shown instead of the model's


def evenly_spaced(items: Sequence[T], count: int) -> list[T]:
    """`count` items spread over the whole list (all of them if there are fewer)."""
    if count >= len(items):
        return list(items)
    return [items[i * len(items) // count] for i in range(count)]


def record_from_hint(hint: HintResult) -> dict[str, Any]:
    """The few numbers of one hint that the summary needs."""
    attempts = hint.attempts
    return {
        "latency_ms": hint.latency_ms,
        "source": hint.source,
        "first_attempt_ok": bool(attempts) and attempts[0].ok,
        "model_seconds": sum((a.latency_ms or 0.0) for a in attempts) / 1000,
        "completion_tokens": sum((a.completion_tokens or 0) for a in attempts),
    }


def summarize(model: str, records: Sequence[dict[str, Any]]) -> Row:
    """Median, p90, speed and the two shares for one model."""
    if not records:
        raise ValueError(f"no hints were made with {model}")
    seconds = sorted(r["latency_ms"] / 1000 for r in records)
    p90 = seconds[math.ceil(0.9 * len(seconds)) - 1]
    model_seconds = sum(r["model_seconds"] for r in records)
    tokens = sum(r["completion_tokens"] for r in records)
    return Row(
        model=model,
        hints=len(records),
        median_s=statistics.median(seconds),
        p90_s=p90,
        tokens_per_s=tokens / model_seconds if model_seconds else 0.0,
        first_blocked_share=sum(not r["first_attempt_ok"] for r in records) / len(records),
        reference_share=sum(r["source"] == "reference" for r in records) / len(records),
    )


def choose_model(
    rows: Sequence[Row],
    *,
    order: Sequence[str],
    max_median_s: float = MAX_MEDIAN_S,
    max_reference: float = MAX_REFERENCE_SHARE,
) -> str:
    """The rule: the largest model (`order` runs smallest to largest) within both limits.

    If none passes, the smallest is used and the caller says so.
    """
    by_name = {row.model: row for row in rows}
    passing = [
        name
        for name in order
        if name in by_name
        and by_name[name].median_s <= max_median_s
        and by_name[name].reference_share <= max_reference
    ]
    return passing[-1] if passing else order[0]


def render_table(rows: Sequence[Row]) -> str:
    """The numbers as a Markdown table."""
    lines = [
        "| model | hints | median s | p90 s | tokens/s | first reply blocked "
        "| teacher's hint shown |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r.model} | {r.hints} | {r.median_s:.1f} | {r.p90_s:.1f} | {r.tokens_per_s:.1f} "
            f"| {r.first_blocked_share:.0%} | {r.reference_share:.0%} |"
        )
    return "\n".join(lines)
