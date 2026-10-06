"""Generate a simulated class: every submission, with its time, code, editor summary and label.

Week 5 Step 1. `generate` is pure: the same problems, pools and config always give the same
cohort (one `random.Random(config.seed)`, used in a fixed order; no clock). The labels (who
cheated, from where, the true skill) are the ground truth for Steps 2-3. They live only in the
cohort file, never in the database rows the detectors read.

How a student works (docs in the Step 1 plan, numbers in `CohortConfig`):
- attempt k on a problem succeeds with sigmoid(θ - b + learning·(k-1)); success draws correct
  code, failure wrong code; stop at success or after the persona's max attempts;
- each submit's time = the previous one + the editor summary's `since_open_ms`, so the times
  and the summaries agree;
- AI users paste 7B answers on their cheating problems; copiers (generated last) paste an
  earlier honest submission of another student, exact, renamed, or renamed and reformatted.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from codetutor.api.schemas import EditorStats
from codetutor.problems import Problem
from codetutor.sim.editor import honest_stats, pasted_stats
from codetutor.sim.personas import CohortConfig, Persona
from codetutor.sim.pools import Pools, Source, SourceKind
from codetutor.sim.transforms import reformat, rename_identifiers

EVENING_START_H = 14  # UTC: 17:00 in Qatar
EVENING_HOURS = 7  # students work between 17:00 and 24:00 Qatar time


class Transform(StrEnum):
    """What was done to the source code before it was submitted."""

    NONE = "none"
    RENAMED = "renamed"  # variables renamed (an honest student's own names, or a disguise)
    RENAMED_REFORMATTED = "renamed_reformatted"  # renamed + printed back (no comments)


class Label(BaseModel):
    """The ground truth of one row. Never stored in the database."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    persona: Persona
    source_kind: SourceKind
    source_ref: str  # a file, a model answer ("<model>#seed7") or the copied row's key
    transform: Transform
    intended_pass: bool  # the source code passed when it was graded before
    cheating: bool  # a copy or a pasted AI answer: what Step 2 should flag


class CohortRow(BaseModel):
    """One simulated submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str  # "<student>/<problem id>/<attempt>", unique
    student: str  # "sim-017": says nothing about the persona
    problem_id: str
    problem_version: int
    attempt: int
    created_at: datetime
    code: str
    editor_stats: dict[str, Any]
    label: Label


class StudentTruth(BaseModel):
    """What only the simulator knows about a student (Step 3 checks its estimates against it)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    persona: Persona
    skill: float  # true θ
    last_module: int  # 8, except for quitters


class Cohort(BaseModel):
    """A whole simulated class."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    config: CohortConfig
    students: list[StudentTruth]
    difficulty: dict[str, float]  # true b per problem id
    rows: list[CohortRow]


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _checked(stats: dict[str, Any]) -> dict[str, Any]:
    """The summary, after the API's own model accepted it (a bug here must fail loudly)."""
    EditorStats.model_validate(stats)
    return stats


def _restyle(
    code: str, problem: Problem, transform: Transform, rng: random.Random
) -> tuple[str, Transform]:
    """Apply a transform; code that doesn't parse (a model's broken answer) stays as it is."""
    if transform == Transform.NONE:
        return code, transform
    try:
        renamed = rename_identifiers(code, problem.function_name, rng)
    except SyntaxError:
        return code, Transform.NONE
    if transform == Transform.RENAMED_REFORMATTED:
        return reformat(renamed), transform
    return renamed, transform


class _Generator:
    """One generation run: the shared random source and the rows made so far."""

    def __init__(self, problems: Sequence[Problem], pools: dict[str, Pools], config: CohortConfig):
        self.problems = sorted(problems, key=lambda p: (p.module, p.order, p.id))
        self.pools = pools
        self.config = config
        self.rng = random.Random(config.seed)
        self.rows: list[CohortRow] = []

    def difficulties(self) -> dict[str, float]:
        base, sd = self.config.difficulty_base, self.config.difficulty_jitter_sd
        return {p.id: base[p.difficulty.value] + self.rng.gauss(0.0, sd) for p in self.problems}

    def students(self) -> list[StudentTruth]:
        personas = [
            persona for persona, spec in self.config.personas.items() for _ in range(spec.count)
        ]
        self.rng.shuffle(personas)  # names in random order: a name never hints at a persona
        low, high = self.config.quitter_last_module
        students = []
        for number, persona in enumerate(personas, start=1):
            spec = self.config.personas[persona]
            students.append(
                StudentTruth(
                    name=f"sim-{number:03d}",
                    persona=persona,
                    skill=self.rng.gauss(spec.skill_mean, self.config.skill_sd),
                    last_module=self.rng.randint(low, high) if persona == Persona.QUITTER else 8,
                )
            )
        return students

    def start_time(self, problem: Problem, earliest_day: float = 0.0) -> datetime:
        """When a student starts a problem: an evening in its module's week."""
        day = self.rng.uniform(earliest_day, 7.0)
        start = self.config.course_start + timedelta(weeks=problem.module - 1, days=int(day))
        seconds = self.rng.uniform(0, EVENING_HOURS * 3600)
        return start + timedelta(hours=EVENING_START_H, seconds=round(seconds))

    def add(
        self,
        student: StudentTruth,
        problem: Problem,
        attempt: int,
        at: datetime,
        code: str,
        stats: dict[str, Any],
        source: Source,
        transform: Transform,
    ) -> CohortRow:
        cheating = source.kind in (SourceKind.COPY, SourceKind.AI)
        row = CohortRow(
            key=f"{student.name}/{problem.id}/{attempt}",
            student=student.name,
            problem_id=problem.id,
            problem_version=problem.version,
            attempt=attempt,
            created_at=at,
            code=code,
            editor_stats=_checked(stats),
            label=Label(
                persona=student.persona,
                source_kind=source.kind,
                source_ref=source.ref,
                transform=transform,
                intended_pass=source.passed,
                cheating=cheating,
            ),
        )
        self.rows.append(row)
        return row

    def work_honestly(
        self, student: StudentTruth, problem: Problem, b: float, at: datetime
    ) -> None:
        config, rng = self.config, self.rng
        spec = config.personas[student.persona]
        pools = self.pools[problem.id]
        for attempt in range(1, spec.max_attempts + 1):
            chance = _sigmoid(student.skill - b + config.learning_per_attempt * (attempt - 1))
            solved = rng.random() < chance
            source = rng.choice(pools.correct if solved else pools.wrong)
            wanted = Transform.RENAMED if rng.random() < config.own_style_share else Transform.NONE
            code, transform = _restyle(source.code, problem, wanted, rng)
            stats = honest_stats(
                rng, code, problem.starter_code, attempt, student.skill, config.honest_paste_share
            )
            at += timedelta(milliseconds=stats["since_open_ms"])
            self.add(student, problem, attempt, at, code, stats, source, transform)
            if source.passed:
                return

    def paste_ai(self, student: StudentTruth, problem: Problem, at: datetime) -> None:
        rng = self.rng
        for attempt in range(1, self.config.ai_max_pastes + 1):
            source = rng.choice(self.pools[problem.id].ai)
            wanted = Transform.RENAMED if rng.random() < 0.3 else Transform.NONE
            code, transform = _restyle(source.code, problem, wanted, rng)
            stats = pasted_stats(rng, code)
            at += timedelta(milliseconds=stats["since_open_ms"])
            self.add(student, problem, attempt, at, code, stats, source, transform)
            if source.passed:
                return

    def copy(self, student: StudentTruth, problem: Problem, b: float) -> None:
        """Paste an earlier honest, passing submission of another student, disguised."""
        rng = self.rng
        at = self.start_time(problem, earliest_day=3.0)  # copiers wait for others to finish
        # Only what existed before the copier even started: the submit comes later still.
        candidates = [
            row
            for row in self.rows
            if row.problem_id == problem.id
            and row.student != student.name
            and not row.label.cheating
            and row.label.intended_pass
            and row.created_at < at
        ]
        if not candidates:  # nobody to copy from yet: this time they do the work
            self.work_honestly(student, problem, b, at)
            return
        original = rng.choice(sorted(candidates, key=lambda row: row.key))
        wanted = rng.choice(list(Transform))
        code, transform = _restyle(original.code, problem, wanted, rng)
        stats = pasted_stats(rng, code)
        done_at = at + timedelta(milliseconds=stats["since_open_ms"])
        source = Source(kind=SourceKind.COPY, ref=original.key, code=original.code, passed=True)
        self.add(student, problem, 1, done_at, code, stats, source, transform)


def generate(problems: Sequence[Problem], pools: dict[str, Pools], config: CohortConfig) -> Cohort:
    """The whole simulated class. Same inputs → the same cohort, row for row."""
    gen = _Generator(problems, pools, config)
    difficulty = gen.difficulties()
    students = gen.students()
    copies: list[tuple[StudentTruth, Problem]] = []
    for student in students:
        spec = config.personas[student.persona]
        for problem in gen.problems:
            if problem.module > student.last_module:
                break  # problems are in module order: a quitter has stopped coming
            cheats = gen.rng.random() < spec.cheat_share
            if cheats and student.persona == Persona.COPIER:
                copies.append((student, problem))  # after everyone else, so sources exist
            elif cheats and student.persona == Persona.AI_USER and gen.pools[problem.id].ai:
                gen.paste_ai(student, problem, gen.start_time(problem))
            else:
                gen.work_honestly(student, problem, difficulty[problem.id], gen.start_time(problem))
    for student, problem in copies:
        gen.copy(student, problem, difficulty[problem.id])
    rows = sorted(gen.rows, key=lambda row: (row.created_at, row.key))
    return Cohort(config=config, students=students, difficulty=difficulty, rows=rows)


def write_cohort(cohort: Cohort, rows_path: Path, meta: dict[str, Any]) -> None:
    """Rows as JSONL (one per line), everything else as a JSON meta file next to it.

    The rows file depends only on the inputs, so it is byte-identical across runs; `meta` may
    add facts about the run (git commit, input file hashes).
    """
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    with rows_path.open("w", encoding="utf-8") as file:
        for row in cohort.rows:
            file.write(row.model_dump_json() + "\n")
    content = {
        "config": cohort.config.model_dump(mode="json"),
        "students": [student.model_dump(mode="json") for student in cohort.students],
        "difficulty": cohort.difficulty,
        "rows": len(cohort.rows),
        **meta,
    }
    meta_path_for(rows_path).write_text(
        json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def meta_path_for(rows_path: Path) -> Path:
    """cohort-s0.jsonl → cohort-s0.meta.json"""
    return rows_path.with_name(rows_path.stem + ".meta.json")


def read_rows(rows_path: Path) -> list[CohortRow]:
    """The rows of a cohort file."""
    lines = rows_path.read_text(encoding="utf-8").splitlines()
    return [CohortRow.model_validate_json(line) for line in lines if line.strip()]
