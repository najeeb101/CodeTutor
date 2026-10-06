"""Synthetic editor summaries for simulated submits (Week 5 Step 1; the fields of Step 0).

Honest work: typing about 1.2-2x the new code (deleted text was typed too), slower for a lower
skill, now and then a small paste of the student's own code (an honest case that looks a bit
like cheating). Pasted work: one big paste, very little typing, a short time. The numbers are
rough on purpose; they only need the right *shape* for Step 2's paste/speed signals. Every
summary keeps the API's rules (EditorStats), and the generator checks that.
"""

from __future__ import annotations

import math
import random
from typing import Any


def _stats(
    *,
    since_open_ms: float,
    active_ms: float,
    typed: int,
    pastes: list[int],
    edits: int,
    restored_draft: bool = False,
) -> dict[str, Any]:
    active = round(active_ms)
    return {
        "since_open_ms": max(round(since_open_ms), active),
        "active_ms": active,
        "typed_chars": typed,
        "pasted_chars": sum(pastes),
        "paste_count": len(pastes),
        "largest_paste_chars": max(pastes, default=0),
        "edit_count": edits,
        "restored_draft": restored_draft,
    }


def honest_stats(
    rng: random.Random, code: str, starter: str, attempt: int, skill: float, paste_share: float
) -> dict[str, Any]:
    """A student writing `code` themselves. Attempt 1 starts from the starter code; a later
    attempt changes part of their previous code."""
    if attempt == 1:
        new_chars = max(10, len(code) - len(starter))
        typed = round(new_chars * rng.uniform(1.2, 2.0))
        reading_s = rng.uniform(10, 120)
    else:
        typed = 3 + round(len(code) * rng.uniform(0.05, 0.4))
        reading_s = rng.uniform(2, 30)  # looking at the last result
    pastes: list[int] = []
    if rng.random() < paste_share:  # e.g. a line copied from their own earlier code
        pastes.append(rng.randint(15, max(15, min(150, len(code) // 2))))
    slower = math.exp(-0.25 * skill)  # a lower skill types and thinks more slowly
    ms_per_char = rng.uniform(180, 450) * slower
    thinking_s = rng.uniform(20, 300) * slower
    active_ms = typed * ms_per_char + thinking_s * 1000
    edits = round(typed / rng.uniform(1.0, 1.4)) + len(pastes)
    return _stats(
        since_open_ms=active_ms + reading_s * 1000,
        active_ms=active_ms,
        typed=typed,
        pastes=pastes,
        edits=edits,
    )


def pasted_stats(rng: random.Random, code: str) -> dict[str, Any]:
    """Code pasted in from somewhere else: one big paste, a few typed characters, fast."""
    typed = rng.randint(0, 25)  # e.g. deleting the starter code's `pass`, a small touch-up
    active_ms = rng.uniform(5, 60) * 1000
    return _stats(
        since_open_ms=active_ms + rng.uniform(5, 90) * 1000,
        active_ms=active_ms,
        typed=typed,
        pastes=[max(1, len(code))],
        edits=typed + 1,
    )


def ide_paste_stats(rng: random.Random, code: str) -> dict[str, Any]:
    """An honest student who wrote `code` in their own editor and pastes it in (Step 2a).

    It looks like `pasted_stats` on purpose: a paste detector can't tell them apart, only
    other evidence can. They sometimes touch it up here, and take a bit longer.
    """
    typed = rng.randint(0, 40)
    active_ms = rng.uniform(10, 120) * 1000
    return _stats(
        since_open_ms=active_ms + rng.uniform(5, 120) * 1000,
        active_ms=active_ms,
        typed=typed,
        pastes=[max(1, len(code))],
        edits=typed + 1,
    )


def retyped_stats(rng: random.Random, code: str) -> dict[str, Any]:
    """A cheater typing a copied program in by hand (Step 2a): no paste at all, but fast and
    with almost no thinking time, because the answer is already in front of them."""
    typed = round(len(code) * rng.uniform(1.0, 1.1))
    active_ms = typed * rng.uniform(60, 120) + rng.uniform(5, 30) * 1000
    return _stats(
        since_open_ms=active_ms + rng.uniform(5, 60) * 1000,
        active_ms=active_ms,
        typed=typed,
        pastes=[],
        edits=round(typed / rng.uniform(1.0, 1.2)),
    )
