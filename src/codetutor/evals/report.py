"""Turn eval runs into one Markdown report (tables only; GitHub renders it).

Deterministic: the same results files always give byte-identical text (sorted rows, fixed number
formats, a fixed bootstrap seed, no "generated at" time). The interpretation of the numbers is
written by hand elsewhere (docs/notes/week2.md); this file only reports.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from codetutor.evals import metrics
from codetutor.evals.metrics import RunData
from codetutor.problems import Problem

HARDEST_PROBLEMS = 8
FAILURE_STATUSES = ["wrong_answer", "runtime_error", "timeout", "compile_error", "crashed"]
SortKey = Callable[[str], Any]


def _num(value: float | None, digits: int = 3) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _cell(text: str) -> str:
    """Text that is safe inside a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _label(run: RunData) -> str:
    """The model name without its provider, plus a mark for an unfinished run."""
    name = run.meta.config.model.partition("/")[2]
    return f"{name} (partial)" if run.is_partial else name


def _runs_section(runs: list[RunData]) -> str:
    rows = []
    for run in runs:
        config, meta = run.meta.config, run.meta
        if config.seed_base is None:
            seeds = "none"
        else:
            seeds = f"{config.seed_base}–{config.seed_base + config.samples - 1}"
        details = meta.model_details
        weights = f"{str(details.get('digest', ''))[:12]} {details.get('quantization', '')}"
        commit = (meta.git_commit or "?")[:7]
        if meta.git_dirty:
            commit += " (uncommitted changes)"
        status = "partial" if run.is_partial else "complete"
        rows.append(
            [
                config.model,
                f"{len(run.records)} / {run.expected} ({status})",
                str(config.samples),
                f"{config.temperature:g}",
                seeds,
                f"prompt {meta.prompt_version}, grader {meta.grader_version}",
                commit,
                weights.strip() or "–",
            ]
        )
    header = ["Model", "Answers", "n", "Temp.", "Seeds", "Versions", "Code", "Weights"]
    return "## 1. Runs\n\n" + _table(header, rows)


def _headline_section(runs: list[RunData]) -> str:
    rows = []
    for run in runs:
        stats = metrics.problem_stats(run.records)
        interval = metrics.bootstrap_ci(stats)
        pass_1 = _num(metrics.pass_at_k_mean(stats, 1))
        if interval is not None:
            pass_1 += f" [{interval[0]:.3f}, {interval[1]:.3f}]"
        failures = metrics.failure_breakdown(run.records)
        latency = metrics.median_of([record.reply.latency_ms for record in run.records])
        reply_tokens = metrics.median_of([r.reply.completion_tokens for r in run.records])
        thinking = metrics.median_of([metrics.thinking_tokens(r) for r in run.records])
        rows.append(
            [
                _label(run),
                pass_1,
                _num(metrics.pass_at_k_mean(stats, 5)),
                _num(metrics.pass_at_k_mean(stats, 10)),
                _num(metrics.mean_reward(stats)),
                f"{failures.hidden_only} of {failures.wrong}",
                str(failures.cut_off),
                str(failures.format_failures),
                "–" if latency is None else f"{latency / 1000:.1f} s",
                _num(reply_tokens, 0),
                _num(thinking, 0),
            ]
        )
    header = [
        "Model",
        "pass@1 [95% interval]",
        "pass@5",
        "pass@10",
        "Mean reward",
        "Hidden-only failures",
        "Cut off",
        "Format failures",
        "Median latency",
        "Median reply tokens",
        "Median thinking tokens",
    ]
    return "## 2. Headline\n\n" + _table(header, rows)


def _group_table(
    name: str,
    runs: list[RunData],
    problems: dict[str, Problem],
    key: metrics.GroupKey,
    sort_key: SortKey = str,
) -> str:
    """One row per group (module, difficulty or concept): pass@1 (mean reward) per model."""
    per_run = [
        metrics.by_group(metrics.problem_stats(run.records), problems, key, sort_key)
        for run in runs
    ]
    labels = sorted({label for groups in per_run for label in groups}, key=sort_key)
    rows = []
    for label in labels:
        counts = sorted({groups[label].problems for groups in per_run if label in groups})
        row = [label, "/".join(str(count) for count in counts)]
        for groups in per_run:
            group = groups.get(label)
            row.append("–" if group is None else f"{group.pass_at_1:.2f} ({group.mean_reward:.2f})")
        rows.append(row)
    return _table([name, "Problems"] + [_label(run) for run in runs], rows)


def _groups_section(runs: list[RunData], problems: dict[str, Problem]) -> str:
    def by_difficulty(label: str) -> int:
        return metrics.DIFFICULTY_ORDER.get(label, 99)

    parts = [
        "## 3. By module, difficulty and concept",
        "Each cell: pass@1 (mean reward). A problem with several concepts counts in each.",
        "### By module\n\n" + _group_table("Module", runs, problems, metrics.module_key),
        "### By difficulty\n\n"
        + _group_table("Difficulty", runs, problems, metrics.difficulty_key, by_difficulty),
        "### By concept\n\n" + _group_table("Concept", runs, problems, metrics.concept_key),
    ]
    return "\n\n".join(parts)


def _failures_section(runs: list[RunData]) -> str:
    per_run = [metrics.failure_breakdown(run.records) for run in runs]
    rows = [["Answers"] + [str(failures.answers) for failures in per_run]]
    rows.append(["Not accepted"] + [str(failures.wrong) for failures in per_run])
    for status in FAILURE_STATUSES:
        rows.append([f"– {status}"] + [str(f.by_status.get(status, 0)) for f in per_run])
    rows.append(["Hidden-only (all visible tests passed)"] + [str(f.hidden_only) for f in per_run])
    rows.append(["Cut off by max_tokens"] + [str(f.cut_off) for f in per_run])
    rows.append(["Code not in a ```python block"] + [str(f.format_failures) for f in per_run])
    header = ["Kind"] + [_label(run) for run in runs]
    return "## 4. Failure types\n\n" + _table(header, rows)


def _hardest_section(runs: list[RunData], problems: dict[str, Problem]) -> str:
    parts = [
        "## 5. Hardest problems",
        f"Up to {HARDEST_PROBLEMS} problems with the lowest pass@1 per model. The note is the "
        "test's own description from tests.yaml.",
    ]
    for run in runs:
        stats = metrics.problem_stats(run.records)
        weak = [(problem_id, s) for problem_id, s in stats.items() if s.c < s.n]
        weak.sort(key=lambda item: (item[1].c / item[1].n, item[0]))
        rows = []
        for problem_id, s in weak[:HARDEST_PROBLEMS]:
            problem = problems[problem_id]
            test = metrics.most_failed_test(run.records, problem)
            if test is None:
                failing = "–"
            else:
                kind = "hidden" if test.hidden else "visible"
                failing = f"{test.test_id} ({kind}, {test.count}×): {test.note or 'no note'}"
            status = metrics.main_failure_status(run.records, problem_id) or "–"
            rows.append([problem_id, problem.difficulty.value, f"{s.c}/{s.n}", failing, status])
        header = ["Problem", "Difficulty", "Passed", "Most failed test", "Main failure"]
        table = _table(header, rows) if rows else "Every answer was accepted."
        parts.append(f"### {_label(run)}\n\n{table}")
    return "\n\n".join(parts)


def _all_problems_section(runs: list[RunData], problems: dict[str, Problem]) -> str:
    per_run = [metrics.problem_stats(run.records) for run in runs]
    problem_ids = sorted(
        {problem_id for stats in per_run for problem_id in stats},
        key=lambda problem_id: (problems[problem_id].module, problems[problem_id].order),
    )
    rows = []
    for problem_id in problem_ids:
        problem = problems[problem_id]
        row = [problem_id, problem.difficulty.value]
        for stats in per_run:
            s = stats.get(problem_id)
            row.append("–" if s is None else f"{s.c}/{s.n} ({s.mean_reward:.2f})")
        rows.append(row)
    header = ["Problem", "Difficulty"] + [_label(run) for run in runs]
    intro = "Each cell: accepted answers / answers (mean reward)."
    return f"## 6. All problems\n\n{intro}\n\n" + _table(header, rows)


HOW_TO_READ = """## 7. How to read this report
- **pass@k**: the chance that at least one of k answers passes every test, estimated without
  bias from n answers per problem (Chen et al. 2021), then averaged over problems. "–" means a
  model has fewer than k answers per problem.
- **95% interval**: a bootstrap over problems (2000 resamples, seed 0). It shows how much pass@1
  depends on which problems are in the bank; it does not include the extra noise from having
  only n answers per problem.
- **Mean reward**: partial credit (passed tests / all tests). Much higher than pass@1 means the
  wrong answers are usually nearly right.
- **Hidden-only failures**: wrong answers that pass every visible test. Without hidden tests
  they would look correct.
- **Thinking tokens**: total − prompt − reply tokens (Gemini reports hidden reasoning only in
  the total).
- Caveats: one prompt version; one temperature; timeouts depend on machine load (the grader is
  deterministic otherwise); a partial run is marked and is not yet comparable."""


def render_report(runs: list[RunData], problems: list[Problem], title: str) -> str:
    """The whole report as Markdown text."""
    by_id = {problem.id: problem for problem in problems}
    parts = [f"# {title}", "Generated by `scripts/eval_report.py` from the results files below."]
    warnings = sorted({w for run in runs for w in metrics.version_warnings(run.records, by_id)})
    if warnings:
        parts.append("**Warnings:**\n" + "\n".join(f"- {warning}" for warning in warnings))
    # Answers for problems that are no longer in the bank are warned about above, then left out.
    runs = [
        RunData(meta=run.meta, records=[r for r in run.records if r.problem_id in by_id])
        for run in runs
    ]
    parts += [
        _runs_section(runs),
        _headline_section(runs),
        _groups_section(runs, by_id),
        _failures_section(runs),
        _hardest_section(runs, by_id),
        _all_problems_section(runs, by_id),
        HOW_TO_READ,
    ]
    return "\n\n".join(parts) + "\n"
