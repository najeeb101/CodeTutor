"""The AI answers the checks know (Week 5 Step 2b).

A real course would ask a few models for answers to every problem and keep them. Here they
are the 7B's Week 2 answers with the reference seeds (0-4). The simulated AI users paste
*other* seeds (5-9), so `same_as_ai` is never tested on the exact text it knows (Step 1a).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from codetutor.evals.records import read_records
from codetutor.integrity.signals import KnownAnswer
from codetutor.problems import Problem
from codetutor.sim.personas import CohortConfig
from codetutor.sim.pools import AI_ANSWERS


def known_ai_answers(
    problems: Sequence[Problem],
    path: Path = AI_ANSWERS,
    seeds: Iterable[int] = CohortConfig().reference_seeds,
) -> dict[str, list[KnownAnswer]]:
    """{problem id: known answers}, in the results file's order. Only answers graded on the
    problem's current version (another version may ask for something else); empty code left
    out."""
    current = {problem.id: problem.version for problem in problems}
    wanted = set(seeds)
    answers: dict[str, list[KnownAnswer]] = {problem.id: [] for problem in problems}
    for record in read_records(path):
        if record.seed not in wanted or current.get(record.problem_id) != record.problem_version:
            continue
        if record.code.strip():
            answers[record.problem_id].append(
                KnownAnswer(ref=f"{record.model}#seed{record.seed}", code=record.code)
            )
    return answers
