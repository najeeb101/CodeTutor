"""The simulated class (Week 5 Step 1): transforms, pools, and the generated cohort."""

from __future__ import annotations

import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codetutor.api.schemas import EditorStats
from codetutor.evals.records import EvalRecord, ModelReply, read_records
from codetutor.grader import SubprocessSandbox, grade_many
from codetutor.grader.models import GradeResult, GradeStatus
from codetutor.problems import Problem
from codetutor.problems.loader import load_all
from codetutor.sim.cohort import Cohort, CohortRow, generate, meta_path_for, read_rows, write_cohort
from codetutor.sim.personas import CohortConfig, Persona
from codetutor.sim.pools import Pools, SourceKind, build_pools
from codetutor.sim.transforms import reformat, renamable_names, rename_identifiers

RESULTS = Path(__file__).resolve().parents[1] / "lab" / "evals" / "results"
HONEST = RESULTS / "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl"
AI = RESULTS / "qwen2.5-coder-7b-q4-t0.8-n10.jsonl"
SANDBOX = SubprocessSandbox()  # the bank's own code, renamed: trusted


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    return load_all()


@pytest.fixture(scope="module")
def pools(bank: list[Problem]) -> dict[str, Pools]:
    return build_pools(bank, read_records(HONEST), read_records(AI), CohortConfig())


@pytest.fixture(scope="module")
def cohort(bank: list[Problem], pools: dict[str, Pools]) -> Cohort:
    return generate(bank, pools, CohortConfig())


def _by_problem_attempts(rows: list[CohortRow]) -> dict[tuple[str, str], list[CohortRow]]:
    groups: dict[tuple[str, str], list[CohortRow]] = defaultdict(list)
    for row in rows:
        groups[(row.student, row.problem_id)].append(row)
    return {key: sorted(items, key=lambda r: r.attempt) for key, items in groups.items()}


# --- Transforms ---


def test_disguised_solutions_still_pass_every_test(bank: list[Problem]) -> None:
    jobs = []
    for seed, problem in enumerate(bank):
        renamed = rename_identifiers(
            problem.solution_code, problem.function_name, random.Random(seed)
        )
        jobs += [(problem, renamed), (problem, reformat(renamed))]
    results = grade_many(jobs, sandbox=SANDBOX, reveal_hidden=False)
    failed = [(problem.id, r.status) for (problem, _), r in zip(jobs, results, strict=True)
              if r.status != GradeStatus.ACCEPTED]  # fmt: skip
    assert failed == []


def test_rename_keeps_builtins_the_function_name_and_keyword_names() -> None:
    code = (
        "def solve(words, key):\n"
        "    total = len(words)  # a comment stays\n"
        "    return sorted(words, key=len)[:total], key\n"
    )
    assert renamable_names(code, "solve") == ["total", "words"]  # `key` is also a keyword arg
    renamed = rename_identifiers(code, "solve", random.Random(0))
    assert renamed.startswith("def solve(") and "len(" in renamed and "key=len" in renamed
    assert "# a comment stays" in renamed and "total" not in renamed.split("#")[0]


def test_rename_keeps_behaviour_with_nested_code_and_f_strings() -> None:
    code = (
        "def show(nums):\n"
        "    def double(v):\n"
        "        return v * 2\n"
        "    squares = [n * n for n in nums]\n"
        "    label = lambda x: f'<{x}:{len(squares)}>'\n"
        "    return [label(double(s)) for s in squares]\n"
    )
    renamed = rename_identifiers(code, "show", random.Random(4))
    before: dict[str, object] = {}
    after: dict[str, object] = {}
    exec(code, before)  # our own test code
    exec(renamed, after)
    assert renamed != code
    assert before["show"]([1, 2, 3]) == after["show"]([1, 2, 3])  # type: ignore[operator]


def test_reformat_drops_comments_and_keeps_meaning() -> None:
    assert reformat("def f(x):  # note\n    return  x+1\n") == "def f(x):\n    return x + 1\n"


# --- Pools ---


def test_bank_files_lose_their_teacher_comments(pools: dict[str, Pools]) -> None:
    fizzbuzz = pools["cs1.loops.fizzbuzz"]
    bank_files = [s for s in (*fizzbuzz.correct, *fizzbuzz.wrong) if s.kind != "honest_model"]
    assert bank_files and all("#" not in source.code for source in bank_files)


def test_reference_and_ai_answers_never_overlap(pools: dict[str, Pools]) -> None:
    for problem_pools in pools.values():
        ai_seeds = {s.ref.rsplit("#seed", 1)[1] for s in problem_pools.ai}
        reference_seeds = {s.ref.rsplit("#seed", 1)[1] for s in problem_pools.reference}
        assert ai_seeds <= {"5", "6", "7", "8", "9"}
        assert reference_seeds <= {"0", "1", "2", "3", "4"}


def test_answers_graded_on_another_problem_version_are_left_out(bank: list[Problem]) -> None:
    problem = bank[0]
    stale = EvalRecord(
        model="ollama/x",
        temperature=0.8,
        seed=5,
        prompt_version="1",
        problem_id=problem.id,
        problem_version=problem.version + 1,
        sample_index=0,
        reply=ModelReply(text="..."),
        code="def f(): pass\n",
        extract_method="raw",
        result=GradeResult(problem_id=problem.id, problem_version=problem.version + 1,
                           status=GradeStatus.ACCEPTED, passed=1, total=1, reward=1.0,
                           tests=[], stdout="", duration_ms=1.0, grader_version="0.2.1"),
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )  # fmt: skip
    pools = build_pools([problem], [stale], [stale], CohortConfig())
    assert [s.kind for s in pools[problem.id].correct] == [SourceKind.SOLUTION]
    assert pools[problem.id].ai == ()


# --- The cohort ---


def test_the_same_seed_gives_the_same_cohort(bank: list[Problem], pools: dict[str, Pools]) -> None:
    # A small class (one student per persona) keeps this fast; the code path is the same.
    small = CohortConfig(
        personas={persona: spec.model_copy(update={"count": 1})
                  for persona, spec in CohortConfig().personas.items()}
    )  # fmt: skip
    first = generate(bank, pools, small)
    assert len(first.students) == len(Persona) and first.rows
    assert generate(bank, pools, small).model_dump_json() == first.model_dump_json()


def test_personas_and_names(cohort: Cohort) -> None:
    config = cohort.config
    counts = defaultdict(int)
    for student in cohort.students:
        counts[student.persona] += 1
        assert re.fullmatch(r"sim-\d{3}", student.name)  # a name never tells the persona
    assert counts == {persona: spec.count for persona, spec in config.personas.items()}


def test_every_editor_summary_keeps_the_api_rules(cohort: Cohort) -> None:
    for row in cohort.rows:
        EditorStats.model_validate(row.editor_stats)


def test_keys_and_times_are_unique_and_attempts_go_up(cohort: Cohort) -> None:
    keys = [row.key for row in cohort.rows]
    assert len(keys) == len(set(keys))
    for (_, _), attempts in _by_problem_attempts(cohort.rows).items():
        assert [row.attempt for row in attempts] == list(range(1, len(attempts) + 1))
        times = [row.created_at for row in attempts]
        assert times == sorted(times) and len(set(times)) == len(times)


def test_a_student_stops_after_a_passing_submission(cohort: Cohort) -> None:
    for attempts in _by_problem_attempts(cohort.rows).values():
        assert all(not row.label.intended_pass for row in attempts[:-1])


def test_copies_come_from_earlier_honest_passing_work_of_someone_else(cohort: Cohort) -> None:
    by_key = {row.key: row for row in cohort.rows}
    copies = [row for row in cohort.rows if row.label.source_kind == SourceKind.COPY]
    assert len(copies) > 30
    for copy in copies:
        original = by_key[copy.label.source_ref]
        assert original.student != copy.student and original.problem_id == copy.problem_id
        assert original.created_at < copy.created_at
        assert original.label.intended_pass and not original.label.cheating
        assert copy.label.persona == Persona.COPIER and copy.label.cheating


def test_ai_users_paste_only_their_seeds(cohort: Cohort) -> None:
    ai_rows = [row for row in cohort.rows if row.label.source_kind == SourceKind.AI]
    assert len(ai_rows) > 30
    for row in ai_rows:
        assert row.label.persona == Persona.AI_USER and row.label.cheating
        assert int(row.label.source_ref.rsplit("#seed", 1)[1]) in cohort.config.ai_user_seeds


def test_quitters_stop_after_their_last_module(cohort: Cohort, bank: list[Problem]) -> None:
    module = {problem.id: problem.module for problem in bank}
    last = {s.name: s.last_module for s in cohort.students}
    quitters = {s.name for s in cohort.students if s.persona == Persona.QUITTER}
    assert quitters and all(last[name] < 8 for name in quitters)
    for row in cohort.rows:
        assert module[row.problem_id] <= last[row.student]


def test_stronger_students_pass_more_often(cohort: Cohort) -> None:
    def share(persona: Persona) -> float:
        rows = [row for row in cohort.rows if row.label.persona == persona]
        return sum(row.label.intended_pass for row in rows) / len(rows)

    assert share(Persona.STRONG) > share(Persona.AVERAGE) > share(Persona.STRUGGLING)


def test_the_cohort_file_round_trips(cohort: Cohort, tmp_path: Path) -> None:
    path = tmp_path / "cohort-s0.jsonl"
    write_cohort(cohort, path, {"git_commit": "abc"})
    assert read_rows(path) == cohort.rows
    meta = meta_path_for(path).read_text(encoding="utf-8")
    assert '"students"' in meta and '"difficulty"' in meta and '"git_commit": "abc"' in meta
