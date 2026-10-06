"""The code a simulated student can submit, per problem (Week 5 Step 1).

Everything comes from files already in the repo, so no model is called:
- correct: the reference solution + the 1.5B's accepted Week 2 answers;
- wrong: the bank's buggy files + the 1.5B's other Week 2 answers;
  (the bank's own files lose their `# comments`: they are teacher notes like "# bug: ...",
  which no student writes, and which would give Step 2's detectors a clue no real class has;
  model answers keep theirs, because models really write them)
- ai: the 7B's answers with the config's `ai_user_seeds` (what simulated AI users paste);
- reference: the 7B's answers with `reference_seeds` (Step 2's "known AI answers"; never
  submitted by anyone in the simulation).
An answer graded on an older problem version is left out (its grade may be out of date).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from codetutor.evals.records import EvalRecord
from codetutor.grader.models import GradeStatus
from codetutor.problems import Problem
from codetutor.sim.personas import CohortConfig
from codetutor.tutor.guardrail import without_comments


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


def build_pools(
    problems: Sequence[Problem],
    honest_answers: Iterable[EvalRecord],
    ai_answers: Iterable[EvalRecord],
    config: CohortConfig,
) -> dict[str, Pools]:
    """{problem id: Pools}. `honest_answers`: the 1.5B run; `ai_answers`: the 7B run."""
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
        pools[problem.id] = Pools(
            correct=(solution, *[s for s in honest_sources if s.passed]),
            wrong=(*buggy, *[s for s in honest_sources if not s.passed]),
            ai=tuple(_answer(r, SourceKind.AI) for r in model_ai if r.seed in config.ai_user_seeds),
            reference=tuple(
                _answer(r, SourceKind.AI) for r in model_ai if r.seed in config.reference_seeds
            ),
        )
    return pools
