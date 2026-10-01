"""Run one model over the problem bank, as a config file describes (the run harness CLI).

Usage:
    uv run --env-file .env python scripts/run_eval.py lab/evals/configs/qwen2.5-coder-1.5b-fp16.yaml
    ... --problems cs1.loops.fizzbuzz,cs1.strings.compress --samples 2    (a quick test run)

Official runs (no overrides) write to lab/evals/results/ (committed); running the same command
again continues where it stopped. Any override (or --scratch) writes to lab/evals/scratch/
(gitignored) and starts fresh, so an official results file only ever comes from its config.

Exit codes: 0 = every answer saved; 2 = stopped early (quota or failed calls), so run the same
command again later to continue; 1 = error.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from pydantic import ValidationError

from codetutor.evals import EvalRecord, ModelError, pass_at_k, read_records
from codetutor.evals.run import (
    RESULTS_DIR,
    SCRATCH_DIR,
    RunConfig,
    RunMismatchError,
    load_run_config,
    make_responder,
    make_sandbox,
    meta_path_for,
    run_eval,
)
from codetutor.grader import SandboxUnavailableError
from codetutor.problems import Problem, load_all


def _select_problems(problem_ids: list[str] | None) -> list[Problem]:
    """The whole bank, or the given problems in the given order. Raises KeyError for a typo."""
    bank = load_all()
    if problem_ids is None:
        return bank
    by_id = {problem.id: problem for problem in bank}
    unknown = [problem_id for problem_id in problem_ids if problem_id not in by_id]
    if unknown:
        raise KeyError(f"unknown problem ids: {', '.join(unknown)}")
    return [by_id[problem_id] for problem_id in problem_ids]


def _show_progress(record: EvalRecord, saved: int, expected: int) -> None:
    latency = record.reply.latency_ms
    seconds = f"{latency / 1000:5.1f} s" if latency is not None else "    -  "
    print(
        f"[{saved:>4}/{expected}] {record.problem_id:<36} #{record.sample_index:<2} "
        f"{record.result.status:<14} {record.result.reward:4.2f}  {seconds}",
        flush=True,
    )


def _quick_look(results_path: Path) -> None:
    """pass@1 and status counts over everything in the file (the full report is Step 4)."""
    records = read_records(results_path)
    if not records:
        return
    per_problem: dict[str, list[bool]] = defaultdict(list)
    for record in records:
        per_problem[record.problem_id].append(record.passed)
    pass_1 = [pass_at_k(len(runs), sum(runs), 1) for runs in per_problem.values()]
    print(f"Quick look: pass@1 = {sum(pass_1) / len(pass_1):.3f} over {len(per_problem)} problems")
    statuses = Counter(str(record.result.status) for record in records)
    print("Answers by status: " + ", ".join(f"{name} {n}" for name, n in statuses.most_common()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path, help="a file in lab/evals/configs/")
    parser.add_argument("--problems", help="comma-separated problem ids (a scratch run)")
    parser.add_argument("--samples", type=int, help="answers per problem (a scratch run)")
    parser.add_argument("--scratch", action="store_true", help="write to lab/evals/scratch/")
    args = parser.parse_args()

    try:
        config = load_run_config(args.config)
        overrides: dict[str, object] = {}
        if args.problems:
            overrides["problems"] = args.problems.split(",")
        if args.samples is not None:
            overrides["samples"] = args.samples
        if overrides:
            config = RunConfig.model_validate({**config.model_dump(), **overrides})
        problems = _select_problems(config.problems)
        responder = make_responder(config)
        sandbox = make_sandbox(config)
    except (OSError, yaml.YAMLError, ValidationError, KeyError, ValueError) as exc:
        parser.error(str(exc))
    except (ModelError, SandboxUnavailableError) as exc:
        parser.error(str(exc))

    scratch = args.scratch or bool(overrides)
    results_path = (SCRATCH_DIR if scratch else RESULTS_DIR) / f"{config.run_id}.jsonl"
    if scratch:  # scratch runs always start fresh
        results_path.unlink(missing_ok=True)
        meta_path_for(results_path).unlink(missing_ok=True)

    kind = "scratch" if scratch else "official"
    print(
        f"Run {config.run_id} ({kind}): {config.model}, {len(problems)} problems x "
        f"{config.samples} samples, temperature {config.temperature}, sandbox {config.sandbox}"
    )
    print(f"Results: {results_path}")
    try:
        summary = run_eval(
            config, problems, responder, sandbox, results_path, on_record=_show_progress
        )
    except (RunMismatchError, ModelError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1

    print(
        f"Saved {summary.added} new answers ({summary.already_done} were already there); "
        f"{summary.missing} still missing."
    )
    for failure in summary.failed_calls:
        print(f"  failed call (not graded): {failure}")
    _quick_look(results_path)
    if summary.missing:
        print(
            f"Stopped early: {summary.stop_reason or 'some calls failed'}. "
            "Run the same command again to continue."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
