"""The "after" report for one fold (Week 6 Step 5): the trained adapter against its baseline.

Deterministic like `baseline.py`: the same results files give byte-identical text. The headline
is the held-out side (problems from the two modules the training never saw), compared problem by
problem with the untrained model through the same eval pipeline.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Sequence
from statistics import mean
from typing import Any

from codetutor.evals import metrics
from codetutor.evals.records import EvalRecord
from codetutor.evals.report import fixed
from codetutor.problems import Problem
from codetutor.rl.baseline import NamedRun, _numbers, _records, _table
from codetutor.rl.dataset import FOLDS, split

STATUSES = ("accepted", "wrong_answer", "runtime_error", "timeout", "compile_error", "crashed")


def pass_rates(records: Sequence[EvalRecord]) -> dict[str, float]:
    """Per problem: the share of answers that passed every test (pass@1)."""
    return {pid: s.c / s.n for pid, s in metrics.problem_stats(list(records)).items()}


def paired(before: dict[str, float], after: dict[str, float]) -> dict[str, Any]:
    """Per-problem differences (after - before) on the problems both runs have."""
    ids = sorted(set(before) & set(after))
    diffs = [after[i] - before[i] for i in ids]
    return {
        "ids": ids,
        "diffs": diffs,
        "mean": mean(diffs) if diffs else None,
        "interval": metrics.bootstrap_mean_ci(diffs),
        "better": sum(d > 0 for d in diffs),
        "worse": sum(d < 0 for d in diffs),
        "same": sum(d == 0 for d in diffs),
    }


def hardcoded_answers(records: Sequence[EvalRecord], bank: dict[str, Problem]) -> list[EvalRecord]:
    """Answers whose code contains a whole visible-test result as a literal.

    A crude test for hard-coding: a list, dict, set or tuple with 2+ items, or a string of 4+
    characters, in the code that equals a visible test's expected value. A correct program
    rarely writes the answer it should compute. It also flags honest tables of fixed words
    (a lookup from digits to names), so it is a pointer for a human, not proof.
    """
    flagged = []
    for record in records:
        problem = bank.get(record.problem_id)
        if problem is None:
            continue
        expected = [t.expected for t in problem.tests if not t.hidden]
        if _has_literal(record.code, expected):
            flagged.append(record)
    return flagged


def _has_literal(code: str, expected: list[Any]) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.List | ast.Tuple | ast.Set | ast.Dict) and _size(node) >= 2:
            pass
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) < 4:
                continue
        else:
            continue
        try:
            value = ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
            continue
        if any(type(value) is type(e) and value == e for e in expected):
            return True
    return False


def _size(node: ast.AST) -> int:
    if isinstance(node, ast.Dict):
        return len(node.keys)
    return len(getattr(node, "elts", []))


def curve_rows(steps: Sequence[dict[str, Any]], width: int = 10) -> list[list[str]]:
    """The training log in blocks of `width` steps: reward, all-equal share, seconds, memory."""
    rows = []
    for start in range(0, len(steps), width):
        block = steps[start : start + width]
        rows.append(
            [
                f"{block[0]['step']}-{block[-1]['step']}",
                fixed(mean(float(s["reward"] or 0.0) for s in block), 2),
                f"{fixed(100 * mean(float(s['flat_group'] or 0.0) for s in block), 0)}%",
                fixed(mean(s["seconds"] for s in block), 0),
                fixed(max(s["peak_vram_gib"] for s in block), 2),
            ]
        )
    return rows


def render_report(
    fold: str,
    before: NamedRun,
    after: NamedRun,
    bank: Sequence[Problem],
    steps: Sequence[dict[str, Any]],
    train_meta: dict[str, Any],
) -> str:
    """The whole fold report as Markdown."""
    train, held_out = split(bank, fold)
    sides = {"held out": held_out, "train": train}
    by_id = {p.id: p for p in bank}
    sections = [
        _intro(fold, train_meta),
        _runs_section(before, after),
        _headline_section(before, after, sides),
        _paired_section(before, after, sides),
        _health_section(before, after, sides, by_id),
        _curve_section(steps),
        _limits(fold, len(held_out), len(train_meta.get("train_problems") or [])),
    ]
    return "\n\n".join(sections) + "\n"


def _intro(fold: str, train_meta: dict[str, Any]) -> str:
    config = train_meta["config"]
    return (
        f"# GRPO on fold {fold}: before and after\n\n"
        f"Qwen2.5-Coder-0.5B-Instruct plus a LoRA adapter (rank {config['lora_rank']}), trained "
        f"for {config['steps']} steps of {config['prompts_per_step']} prompts x "
        f"{config['num_generations']} answers, reward `{config['reward_mode']}`, learning rate "
        f"{config['learning_rate']:g}, seed {config['seed']}. Fold {fold} holds out modules "
        f"{', '.join(str(m) for m in FOLDS[fold])}: the **held-out** rows are problems the "
        "training never used. Both runs went through the same eval pipeline (all 33 problems, "
        "10 answers each, temperature 0.8, plain sampling, graded in Docker). Generated by "
        "`scripts/rl_after.py report`."
    )


def _runs_section(before: NamedRun, after: NamedRun) -> str:
    rows = []
    for run in (before, after):
        meta = run.data.meta
        commit = meta.git_commit[:7] if meta.git_commit else "–"
        rows.append(
            [
                run.label,
                f"{len(run.data.records)} of {run.data.expected}",
                meta.config.adapter or "–",
                str(meta.model_details.get("adapter_sha256", "–"))[:12],
                f"{commit}{' (dirty)' if meta.git_dirty else ''}",
            ]
        )
    header = ["Run", "Answers", "Adapter", "Adapter sha256", "Code at start"]
    return "## 1. The runs\n\n" + _table(header, rows)


def _headline_section(
    before: NamedRun, after: NamedRun, sides: dict[str, Sequence[Problem]]
) -> str:
    rows = []
    for side, problems in sides.items():
        ids = {p.id for p in problems}
        for run in (before, after):
            n = _numbers(_records(run, ids))
            rows.append([side, run.label, n["problems"], n["pass1"], n["pass5"], n["reward"]])
    header = ["Side", "Run", "Problems", "pass@1 [95%]", "pass@5", "Mean reward"]
    return (
        "## 2. Before and after\n\n"
        "The intervals resample the problems of that side; with 8 held-out problems they are "
        "wide.\n\n" + _table(header, rows)
    )


def _paired_section(before: NamedRun, after: NamedRun, sides: dict[str, Sequence[Problem]]) -> str:
    parts = ["## 3. The same problems, one by one (pass@1: share of the 10 answers that passed)"]
    summary = []
    for side, problems in sides.items():
        ids = {p.id for p in problems}
        b = pass_rates(_records(before, ids))
        a = pass_rates(_records(after, ids))
        pair = paired(b, a)
        interval = pair["interval"]
        shown = "–" if interval is None else f"[{_signed(interval[0])}, {_signed(interval[1])}]"
        summary.append(
            [
                side,
                str(len(pair["ids"])),
                _signed(pair["mean"]),
                shown,
                f"{pair['better']} / {pair['worse']} / {pair['same']}",
            ]
        )
        if side == "held out":
            rows = [
                [f"`{pid}`", fixed(b[pid], 1), fixed(a[pid], 1), _signed(a[pid] - b[pid])]
                for pid in pair["ids"]
            ]
            held_table = _table(["Held-out problem", "Before", "After", "Change"], rows)
    parts.append(
        _table(
            ["Side", "Problems", "Mean change", "95% interval", "Better / worse / same"],
            summary,
        )
    )
    parts.append(held_table)
    return "\n\n".join(parts)


def _signed(value: float | None) -> str:
    if value is None:
        return "–"
    text = fixed(abs(value), 2)
    return text if text == "0.00" else ("+" if value > 0 else "−") + text


def _health_section(
    before: NamedRun,
    after: NamedRun,
    sides: dict[str, Sequence[Problem]],
    bank: dict[str, Problem],
) -> str:
    rows = []
    for side, problems in sides.items():
        ids = {p.id for p in problems}
        for run in (before, after):
            records = _records(run, ids)
            total = len(records) or 1
            status = Counter(r.result.status.value for r in records)
            methods = Counter(r.extract_method.value for r in records)
            cut = sum(r.reply.finish_reason == "length" for r in records)
            lengths = [r.reply.completion_tokens for r in records if r.reply.completion_tokens]
            flagged = hardcoded_answers(records, bank)
            rows.append(
                [
                    side,
                    run.label,
                    ", ".join(f"{s} {status[s]}" for s in STATUSES if status[s]),
                    f"{methods['python_block']} / {total}",
                    f"{fixed(100 * cut / total, 1)}%",
                    fixed(mean(lengths), 0) if lengths else "–",
                    f"{len(flagged)}",
                ]
            )
    header = [
        "Side",
        "Run",
        "Grades",
        "Answers in a python block",
        "Cut off",
        "Mean tokens",
        "Visible result written out",
    ]
    return (
        "## 4. Did the answers change in other ways?\n\n"
        '"Visible result written out": answers whose code contains a whole expected result of a '
        "visible test as a literal (the crude hard-coding check; correct code seldom does that, "
        "but a lookup table of fixed words also counts). Reading the flagged answers is for a "
        "human.\n\n" + _table(header, rows)
    )


def _curve_section(steps: Sequence[dict[str, Any]]) -> str:
    header = ["Steps", "Mean reward", "All-equal steps", "Seconds per step", "Peak GPU GiB"]
    return (
        "## 5. The training curve\n\n"
        "Each step has different problems, so the reward moves with which problems came up: "
        "it is not a learning curve.\n\n" + _table(header, curve_rows(steps))
    )


def _limits(fold: str, held_out: int, trained_on: int) -> str:
    return (
        "## 6. What this can and cannot say\n\n"
        f"- **One fold, one seed, one run.** Fold {fold} was chosen before any result "
        "(largest room to improve); the other folds follow in Week 7 with the same settings.\n"
        f"- **{held_out} held-out problems.** One problem is a swing of "
        f"{fixed(100 / held_out, 0)} points of pass@1; read the intervals, not the point values.\n"
        f"- **Training used {trained_on} problems** (those whose baseline group was mixed), "
        "each seen many times: the train rows show how much it was memorised.\n"
        "- **Held-out means a different topic, not an unrelated skill** (docs/rl.md §2).\n"
        "- **A LoRA adapter** can learn less than full fine-tuning. The sampling seed is fixed, "
        "so a rerun gives the same answers, but a different seed could move the numbers.\n"
        "- **The hard-coding check is crude** and cannot see a trick that does not write the "
        "answer out."
    )
