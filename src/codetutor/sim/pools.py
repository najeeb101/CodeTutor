"""The code a simulated student can submit, per problem (Week 5 Step 1).

Everything comes from files already in the repo, so no model is called:
- correct: the reference solution + the 1.5B's accepted Week 2 answers + (Step 2a) the
  accepted answers of the Week 4 tutor eval, where the 1.5B fixed a buggy file;
- wrong: the bank's buggy files + the 1.5B's other Week 2 and tutor-eval answers;
  (the bank's own files lose their `# comments`: they are teacher notes like "# bug: ...",
  which no student writes, and which would give Step 2's detectors a clue no real class has;
  model answers keep theirs, because models really write them)
- ai: the 7B's answers with the config's `ai_user_seeds` (what simulated AI users paste);
- reference: the 7B's answers with `reference_seeds` (Step 2's "known AI answers"; never
  submitted by anyone in the simulation).
An answer graded on an older problem version is left out (its grade may be out of date).
Each pile keeps every distinct program once (the first in a fixed order), so a program the
model wrote ten times isn't ten times as likely: the class gets as much variety as the
sources have.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from codetutor.evals.records import EvalRecord, read_records
from codetutor.grader.models import GradeStatus
from codetutor.problems import Problem
from codetutor.sim.personas import CohortConfig
from codetutor.tutor.guardrail import without_comments
from codetutor.tutor.tutor_eval import meta_path_for as tutor_meta_path


class SourceKind(StrEnum):
    """Where a piece of simulated code came from (part of each row's label)."""

    SOLUTION = "solution"  # the bank's solution.py
    BUGGY = "buggy"  # one of the bank's buggy files
    HONEST_MODEL = "honest_model"  # a 1.5B Week 2 answer, standing in for a student's own code
    AI = "ai"  # a 7B Week 2 answer, pasted by an AI user
    COPY = "copy"  # another simulated student's submission (copiers)


class Source(BaseModel):
    """One piece of code and where it came from."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SourceKind
    ref: str  # "solution.py", "buggy/off_by_one.py", "<model>#seed3", or a cohort row key
    code: str
    passed: bool  # accepted when it was graded (the bank's validator, or Week 2)


class Pools(BaseModel):
    """The four piles of code for one problem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correct: tuple[Source, ...]
    wrong: tuple[Source, ...]
    ai: tuple[Source, ...]
    reference: tuple[Source, ...]


def _answer(record: EvalRecord, kind: SourceKind) -> Source:
    return Source(
        kind=kind,
        ref=f"{record.model}#seed{record.seed}",
        code=record.code,
        passed=record.result.status == GradeStatus.ACCEPTED,
    )


def tutor_eval_sources(
    records: Iterable[dict[str, Any]], graded_versions: dict[str, int], problems: Sequence[Problem]
) -> dict[str, list[Source]]:
    """The tutor eval's graded student answers as honest code, per problem (Step 2a).

    `records`: the tutor eval's JSONL rows (tutor/tutor_eval.py); `graded_versions`: its meta's
    problem versions. Answers for a problem whose version changed since are left out.
    """
    current = {problem.id: problem.version for problem in problems}
    sources: dict[str, list[Source]] = {problem.id: [] for problem in problems}
    for record in records:
        if record.get("kind") != "answer" or not record.get("code", "").strip():
            continue
        problem_id = record["situation"].split("/", 1)[0]
        if problem_id not in current or graded_versions.get(problem_id) != current[problem_id]:
            continue
        ref = f"tutor-eval:{record['situation']}#{record['condition']}#{record['sample_index']}"
        sources[problem_id].append(
            Source(
                kind=SourceKind.HONEST_MODEL,
                ref=ref,
                code=record["code"],
                passed=record["status"] == GradeStatus.ACCEPTED,
            )
        )
    return sources


def _distinct(sources: Iterable[Source]) -> tuple[Source, ...]:
    seen: set[str] = set()
    kept = []
    for source in sources:
        if source.code not in seen:
            seen.add(source.code)
            kept.append(source)
    return tuple(kept)


def build_pools(
    problems: Sequence[Problem],
    honest_answers: Iterable[EvalRecord],
    ai_answers: Iterable[EvalRecord],
    config: CohortConfig,
    extra_honest: dict[str, list[Source]] | None = None,
) -> dict[str, Pools]:
    """{problem id: Pools}. `honest_answers`: the 1.5B run; `ai_answers`: the 7B run;
    `extra_honest`: more honest code per problem (`tutor_eval_sources`)."""
    current = {problem.id: problem.version for problem in problems}

    def usable(record: EvalRecord) -> bool:
        return current.get(record.problem_id) == record.problem_version

    honest: dict[str, list[EvalRecord]] = {problem.id: [] for problem in problems}
    for record in honest_answers:
        if usable(record):
            honest[record.problem_id].append(record)
    ai: dict[str, list[EvalRecord]] = {problem.id: [] for problem in problems}
    for record in ai_answers:
        if usable(record):
            ai[record.problem_id].append(record)

    pools: dict[str, Pools] = {}
    for problem in problems:
        answers = sorted(honest[problem.id], key=lambda r: r.sample_index)
        model_ai = sorted(ai[problem.id], key=lambda r: r.sample_index)
        solution = Source(
            kind=SourceKind.SOLUTION,
            ref="solution.py",
            code=without_comments(problem.solution_code),
            passed=True,
        )
        buggy = [
            Source(
                kind=SourceKind.BUGGY,
                ref=f"buggy/{name}.py",
                code=without_comments(code),
                passed=False,
            )
            for name, code in sorted(problem.buggy.items())
        ]
        honest_sources = [_answer(record, SourceKind.HONEST_MODEL) for record in answers]
        honest_sources += sorted((extra_honest or {}).get(problem.id, []), key=lambda s: s.ref)
        pools[problem.id] = Pools(
            correct=_distinct([solution, *[s for s in honest_sources if s.passed]]),
            wrong=_distinct([*buggy, *[s for s in honest_sources if not s.passed]]),
            ai=tuple(_answer(r, SourceKind.AI) for r in model_ai if r.seed in config.ai_user_seeds),
            reference=tuple(
                _answer(r, SourceKind.AI) for r in model_ai if r.seed in config.reference_seeds
            ),
        )
    return pools


# The repo files the default pools come from (scripts/sim_cohort.py and the tests use them).
_REPO = Path(__file__).resolve().parents[3]
HONEST_ANSWERS = _REPO / "lab" / "evals" / "results" / "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl"
AI_ANSWERS = _REPO / "lab" / "evals" / "results" / "qwen2.5-coder-7b-q4-t0.8-n10.jsonl"
TUTOR_ANSWERS = (
    _REPO / "lab" / "tutor" / "results" / "tutor-eval-ollama-qwen2.5-coder-1.5b-instruct-fp16.jsonl"
)
INPUT_FILES = (HONEST_ANSWERS, AI_ANSWERS, TUTOR_ANSWERS)


def default_pools(problems: Sequence[Problem], config: CohortConfig) -> dict[str, Pools]:
    """The pools from the committed Week 2 runs and the Week 4 tutor eval (no model calls)."""
    tutor_records = [
        json.loads(line) for line in TUTOR_ANSWERS.read_text(encoding="utf-8").splitlines() if line
    ]
    tutor_meta = json.loads(tutor_meta_path(TUTOR_ANSWERS).read_text(encoding="utf-8"))
    extra = tutor_eval_sources(tutor_records, tutor_meta["problem_versions"], problems)
    return build_pools(
        problems, read_records(HONEST_ANSWERS), read_records(AI_ANSWERS), config, extra
    )
