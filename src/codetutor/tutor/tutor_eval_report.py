"""The tutor eval's report: fix rates per condition and the paired help of each hint.

Pure functions over the saved records (tutor/tutor_eval.py), so the report can be rebuilt any
time and is byte-identical for the same records. Every situation counts equally: first a fix
rate per situation (its accepted answers / its answers), then the mean over situations.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

from codetutor.evals.metrics import bootstrap_mean_ci
from codetutor.evals.report import fixed
from codetutor.tutor.tutor_eval import CONDITIONS, TUTOR_LEVELS, meta_path_for

READING_LIST = 3  # situations shown where a tutor hint helped most / hurt most
BASELINE = "none"

HOW_TO_READ = """\
How to read it. **Fix rate** = the share of a situation's answers that are accepted, averaged
over situations (every situation counts the same). **Help** = the condition's fix rate minus the
no-hint fix rate *in the same situations* (a paired difference), with a 95% bootstrap interval
over situations. If `tutor-1` comes close to `teacher-3` (the bottom-out hint), the tutor gives
away too much at level 1. If `tutor-k` is below `teacher-k`, the tutor's hints help less than
the teacher's text of the same level."""

LIMITS = """\
Limits. The student is a small language model, not a person: a hint that helps a model fix code
may not teach a human, and a model may fix the code by rewriting the whole function without
using the hint. One student model and one tutor model. Each situation is one buggy file; with
50 situations, one situation moves a rate by 2 points. The teacher's hints, the buggy files and
the course notes were all written by the same author (Claude)."""


@dataclass(frozen=True)
class ConditionStats:
    """One condition's numbers over the situations that have answers for it."""

    condition: str
    situations: int
    answers: int
    fix_rate: float
    interval: tuple[float, float] | None
    mean_reward: float
    help: float | None  # paired difference to the baseline (None for the baseline itself)
    help_interval: tuple[float, float] | None
    better: int
    worse: int
    same: int


def fix_rates(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """{condition: {situation: share of its answers that were accepted}}."""
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for record in records:
        if record["kind"] != "answer":
            continue
        count = counts[(record["condition"], record["situation"])]
        count[0] += record["status"] == "accepted"
        count[1] += 1
    rates: dict[str, dict[str, float]] = defaultdict(dict)
    for (condition, situation), (accepted, total) in sorted(counts.items()):
        rates[condition][situation] = accepted / total
    return rates


def _rewards(records: Sequence[dict[str, Any]]) -> dict[str, dict[str, float]]:
    values: dict[tuple[str, str], list[float]] = defaultdict(list)
    for record in records:
        if record["kind"] == "answer":
            values[(record["condition"], record["situation"])].append(record["reward"])
    rewards: dict[str, dict[str, float]] = defaultdict(dict)
    for (condition, situation), items in sorted(values.items()):
        rewards[condition][situation] = mean(items)
    return rewards


def condition_stats(records: Sequence[dict[str, Any]]) -> list[ConditionStats]:
    """The numbers per condition, in CONDITIONS order (conditions without answers left out)."""
    rates = fix_rates(records)
    rewards = _rewards(records)
    answers: dict[str, int] = defaultdict(int)
    for record in records:
        if record["kind"] == "answer":
            answers[record["condition"]] += 1
    base = rates.get(BASELINE, {})
    stats = []
    for condition in CONDITIONS:
        own = rates.get(condition)
        if not own:
            continue
        values = [own[situation] for situation in sorted(own)]
        paired = sorted(set(own) & set(base)) if condition != BASELINE else []
        diffs = [own[situation] - base[situation] for situation in paired]
        stats.append(
            ConditionStats(
                condition=condition,
                situations=len(own),
                answers=answers[condition],
                fix_rate=mean(values),
                interval=bootstrap_mean_ci(values),
                mean_reward=mean(rewards[condition][s] for s in sorted(own)),
                help=mean(diffs) if diffs else None,
                help_interval=bootstrap_mean_ci(diffs) if diffs else None,
                better=sum(diff > 0 for diff in diffs),
                worse=sum(diff < 0 for diff in diffs),
                same=sum(diff == 0 for diff in diffs),
            )
        )
    return stats


def _num(value: float | None, digits: int = 2, sign: bool = False) -> str:
    if value is None:
        return "–"
    text = fixed(value, digits)
    return f"+{text}" if sign and value > 0 else text


def _interval(interval: tuple[float, float] | None, sign: bool = False) -> str:
    if interval is None:
        return ""
    return f" [{_num(interval[0], sign=sign)}, {_num(interval[1], sign=sign)}]"


def _stats_table(stats: Sequence[ConditionStats]) -> list[str]:
    lines = [
        "| Condition | Situations | Answers | Fix rate [95%] | Mean reward | Help vs none [95%] "
        "| Better / worse / same |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in stats:
        help_text = _num(item.help, sign=True) + _interval(item.help_interval, sign=True)
        counts = "–" if item.help is None else f"{item.better} / {item.worse} / {item.same}"
        lines.append(
            f"| `{item.condition}` | {item.situations} | {item.answers} "
            f"| {_num(item.fix_rate)}{_interval(item.interval)} | {_num(item.mean_reward)} "
            f"| {help_text} | {counts} |"
        )
    return lines


def _hint_table(records: Sequence[dict[str, Any]]) -> list[str]:
    hints = [record for record in records if record["kind"] == "hint"]
    if not hints:
        return ["No tutor hints in these results yet."]
    lines = [
        "| Level | Hints | The tutor's own | Teacher's hint (fallback) | Words (median) |",
        "|---|---|---|---|---|",
    ]
    for level in TUTOR_LEVELS:
        items = [hint for hint in hints if hint["level"] == level]
        if not items:
            continue
        own = sum(hint["source"] == "model" for hint in items)
        words = median(len(hint["text"].split()) for hint in items)
        lines.append(f"| {level} | {len(items)} | {own} | {len(items) - own} | {fixed(words, 0)} |")
    return lines


def _reading_list(records: Sequence[dict[str, Any]], condition: str) -> list[str]:
    rates = fix_rates(records)
    own, base = rates.get(condition, {}), rates.get(BASELINE, {})
    paired = sorted(set(own) & set(base))
    if not paired:
        return []
    hints = {r["situation"]: r["hint"] for r in records if r.get("condition") == condition}
    by_help = sorted(paired, key=lambda s: (own[s] - base[s], s))
    lines = [f"### Where `{condition}` helped most and hurt most", ""]
    for title, picked in (
        ("Helped most", by_help[::-1][:READING_LIST]),
        ("Hurt most", by_help[:READING_LIST]),
    ):
        lines.append(f"**{title}:**")
        lines.append("")
        for situation in picked:
            diff = own[situation] - base[situation]
            lines.append(
                f"- `{situation}`: {_num(base[situation])} → {_num(own[situation])} "
                f"({_num(diff, sign=True)}). Hint: “{hints.get(situation, '')}”"
            )
        lines.append("")
    return lines


def render_report(records: Sequence[dict[str, Any]], results: Path) -> str:
    """The Markdown report for one results file."""
    meta_path = meta_path_for(results)
    settings = ""
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        s = meta["settings"]
        settings = (
            f"Student `{s['student']}` (temperature {s['temperature']:g}, {s['samples']} "
            f"answers per situation and condition, seeds {s['seed_base']}…), tutor "
            f"`{s['tutor']}`; student prompt v{meta['student_prompt_version']}, tutor prompt "
            f"v{meta['tutor_prompt_version']}, grader {meta['grader_version']}."
        )
    stats = condition_stats(records)
    lines = [
        "# Tutor eval: does a hint help a student fix a hidden-only bug?",
        "",
        f"Generated by `scripts/tutor_eval.py` from `{results.name}` (docs/tutor.md §5). "
        "Do not edit by hand.",
        "",
        settings,
        "",
        HOW_TO_READ,
        "",
        "## Fix rate per condition",
        "",
        *(_stats_table(stats) if stats else ["No answers yet."]),
        "",
        "## The tutor's hints",
        "",
        *_hint_table(records),
        "",
    ]
    for condition in ("tutor-1", "tutor-2"):
        lines += _reading_list(records, condition)
    lines += [LIMITS, ""]
    return "\n".join(lines)
