"""Tests for eval metrics and the report, on hand-made records (no grading, so no waiting)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codetutor.evals import EvalRecord, ExtractMethod, ModelReply, pass_at_k
from codetutor.evals import metrics as m
from codetutor.evals.report import render_report
from codetutor.evals.run import REPO_ROOT, RunConfig, RunMeta
from codetutor.grader import GradeResult, GradeStatus, TestResult, TestStatus
from codetutor.problems import Problem, load_all

FIZZ = "cs1.loops.fizzbuzz"  # module 3; concepts for_loops, conditionals, lists; t05+ hidden
MAX3 = "cs1.conditions.max_of_three"  # module 2; concepts conditionals, edge_cases; t05+ hidden


@pytest.fixture(scope="module")
def bank() -> dict[str, Problem]:
    return {problem.id: problem for problem in load_all()}


def record(
    problem: Problem,
    sample: int = 0,
    failed: tuple[str, ...] = (),
    status: GradeStatus | None = None,
    finish: str = "stop",
    method: ExtractMethod = ExtractMethod.PYTHON_BLOCK,
    version: int | None = None,
) -> EvalRecord:
    """One answer. `failed` = ids of the tests it fails; compile_error means no tests ran."""
    tests = []
    if status != GradeStatus.COMPILE_ERROR:
        for test in problem.tests:
            outcome = TestStatus.WRONG_ANSWER if test.id in failed else TestStatus.PASSED
            tests.append(
                TestResult(
                    test_id=test.id,
                    hidden=test.hidden,
                    status=outcome,
                    revealed=True,
                    duration_ms=1.0,
                )
            )
    passed = sum(test.status == TestStatus.PASSED for test in tests)
    if status is None:
        status = GradeStatus.WRONG_ANSWER if failed else GradeStatus.ACCEPTED
    result = GradeResult(
        problem_id=problem.id,
        problem_version=problem.version if version is None else version,
        status=status,
        passed=passed,
        total=len(problem.tests),
        reward=round(passed / len(problem.tests), 4),
        tests=tests,
        stdout="",
        duration_ms=1.0,
    )
    reply = ModelReply(
        text="",
        latency_ms=100.0,
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=40,  # 25 hidden thinking tokens
        finish_reason=finish,
    )
    return EvalRecord(
        model="fake/x",
        temperature=0.8,
        prompt_version="1",
        problem_id=problem.id,
        problem_version=result.problem_version,
        sample_index=sample,
        reply=reply,
        code="",
        extract_method=method,
        result=result,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


def run_data(records: list[EvalRecord], problems: list[Problem], samples: int, model: str):
    config = RunConfig(
        run_id="r", model=model, samples=samples, temperature=0.8, max_tokens=99, seed_base=0
    )
    meta = RunMeta(
        config=config,
        prompt_version="1",
        grader_version="0.2.1",
        problem_versions={problem.id: problem.version for problem in problems},
        model_details={},
        git_commit="abc1234def",
        git_dirty=False,
        started_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    return m.RunData(meta=meta, records=records)


# --- pass@k and groups ---


def test_problem_stats_and_pass_at_k(bank: dict[str, Problem]) -> None:
    fizz = bank[FIZZ]
    records = [record(fizz, i, failed=() if i < 3 else ("t01",)) for i in range(10)]
    stats = m.problem_stats(records)
    assert (stats[FIZZ].n, stats[FIZZ].c) == (10, 3)
    assert m.pass_at_k_mean(stats, 1) == pytest.approx(0.3)
    assert m.pass_at_k_mean(stats, 5) == pytest.approx(pass_at_k(10, 3, 5))
    assert m.pass_at_k_mean(stats, 11) is None  # fewer answers than k


def test_every_problem_counts_equally(bank: dict[str, Problem]) -> None:
    records = [record(bank[FIZZ], i) for i in range(10)] + [record(bank[MAX3], 0, ("t05",))]
    stats = m.problem_stats(records)
    assert m.pass_at_k_mean(stats, 1) == pytest.approx(0.5)  # not 10/11


def test_groups_count_a_problem_in_each_of_its_concepts(bank: dict[str, Problem]) -> None:
    stats = m.problem_stats([record(bank[FIZZ]), record(bank[MAX3], failed=("t05",))])
    concepts = m.by_group(stats, bank, m.concept_key)
    assert concepts["conditionals"].problems == 2  # both problems have it
    assert concepts["conditionals"].pass_at_1 == pytest.approx(0.5)
    assert concepts["for_loops"].problems == 1
    modules = m.by_group(stats, bank, m.module_key)
    assert list(modules) == ["2. Conditions", "3. Loops"]


# --- failures ---


@pytest.mark.parametrize(
    ("failed", "status", "expected"),
    [
        ((), None, False),  # accepted
        (("t05",), None, True),  # only a hidden test fails
        (("t01", "t05"), None, False),  # a visible test fails too
        (("t01",), None, False),  # only a visible test fails
        ((), GradeStatus.COMPILE_ERROR, False),  # no tests ran
    ],
)
def test_hidden_only(
    bank: dict[str, Problem], failed: tuple[str, ...], status: GradeStatus | None, expected: bool
) -> None:
    assert m.is_hidden_only(record(bank[MAX3], failed=failed, status=status)) is expected


def test_failure_breakdown(bank: dict[str, Problem]) -> None:
    max3 = bank[MAX3]
    records = [
        record(max3, 0),
        record(max3, 1, failed=("t05",)),
        record(max3, 2, failed=("t01",), status=GradeStatus.RUNTIME_ERROR),
        record(max3, 3, status=GradeStatus.COMPILE_ERROR, finish="length"),
        record(max3, 4, method=ExtractMethod.RAW),
    ]
    failures = m.failure_breakdown(records)
    assert (failures.answers, failures.wrong) == (5, 3)
    assert failures.by_status == {"wrong_answer": 1, "runtime_error": 1, "compile_error": 1}
    assert (failures.hidden_only, failures.cut_off, failures.format_failures) == (1, 1, 1)


def test_most_failed_test_brings_its_note(bank: dict[str, Problem]) -> None:
    max3 = bank[MAX3]
    records = [record(max3, i, failed=("t05",)) for i in range(3)] + [record(max3, 3, ("t09",))]
    test = m.most_failed_test(records, max3)
    assert test is not None
    assert (test.test_id, test.hidden, test.count) == ("t05", True, 3)
    assert test.note == "tie for the largest (first two)"
    assert m.main_failure_status(records, MAX3) == "wrong_answer"


def test_most_failed_test_ties_pick_the_lowest_id(bank: dict[str, Problem]) -> None:
    max3 = bank[MAX3]
    records = [record(max3, 0, failed=("t09",)), record(max3, 1, failed=("t05",))]
    test = m.most_failed_test(records, max3)
    assert test is not None and test.test_id == "t05"


# --- bootstrap, tokens, partial runs, versions ---


def test_bootstrap_interval(bank: dict[str, Problem]) -> None:
    mixed = m.problem_stats(
        [record(bank[FIZZ], i, () if i % 2 else ("t01",)) for i in range(4)]
        + [record(bank[MAX3], i) for i in range(4)]
    )
    interval = m.bootstrap_ci(mixed)
    pass_1 = m.pass_at_k_mean(mixed, 1)
    assert interval is not None and pass_1 is not None
    assert interval[0] <= pass_1 <= interval[1]
    assert m.bootstrap_ci(mixed) == m.bootstrap_ci(mixed)  # same seed, same interval
    perfect = m.problem_stats([record(bank[FIZZ], i) for i in range(4)])
    assert m.bootstrap_ci(perfect) == (1.0, 1.0)
    assert m.bootstrap_ci(perfect, k=5) is None  # fewer answers than k


def test_thinking_tokens(bank: dict[str, Problem]) -> None:
    answer = record(bank[FIZZ])
    assert m.thinking_tokens(answer) == 25  # 40 - 10 - 5
    no_total = answer.model_copy(
        update={"reply": answer.reply.model_copy(update={"total_tokens": None})}
    )
    assert m.thinking_tokens(no_total) is None


def test_partial_runs_and_version_warnings(bank: dict[str, Problem]) -> None:
    fizz, max3 = bank[FIZZ], bank[MAX3]
    partial = run_data([record(fizz, 0)], [fizz, max3], samples=1, model="fake/x")
    assert partial.is_partial
    old = record(fizz, 0, version=fizz.version + 5)
    [warning] = m.version_warnings([old], bank)
    assert "graded on version" in warning and FIZZ in warning


# --- the report ---


def _two_runs(bank: dict[str, Problem]) -> list[m.RunData]:
    fizz, max3 = bank[FIZZ], bank[MAX3]
    complete = run_data(
        [record(fizz, 0), record(fizz, 1, ("t01",)), record(max3, 0, ("t05",)), record(max3, 1)],
        [fizz, max3],
        samples=2,
        model="ollama/small-model",
    )
    partial = run_data([record(fizz, 0)], [fizz, max3], samples=1, model="gemini/big-model")
    return [complete, partial]


def test_report_is_deterministic_and_has_every_section(bank: dict[str, Problem]) -> None:
    runs = _two_runs(bank)
    text = render_report(runs, list(bank.values()), "Test report")
    assert text == render_report(runs, list(bank.values()), "Test report")
    for header in [
        "## 1. Runs",
        "## 2. Headline",
        "## 3. By module",
        "## 4. Failure types",
        "## 5. Hardest problems",
        "## 6. All problems",
        "## 7. How to read",
    ]:
        assert header in text
    assert "big-model (partial)" in text
    assert "| – |" in text  # pass@5 can't be computed from 2 answers per problem
    assert "tie for the largest (first two)" in text  # the failing test's note


def test_report_survives_a_removed_problem(bank: dict[str, Problem]) -> None:
    runs = _two_runs(bank)
    without_max3 = [problem for problem in bank.values() if problem.id != MAX3]
    text = render_report(runs, without_max3, "Test report")
    assert f"{MAX3}: no longer in the bank" in text


@pytest.mark.parametrize(
    ("run_id", "pass_1", "wrong", "hidden_only"),
    [
        ("qwen2.5-coder-1.5b-fp16-t0.8-n10", 0.867, 44, 15),
        ("qwen2.5-coder-7b-q4-t0.8-n10", 0.945, 18, 9),
    ],
)
def test_official_results_keep_their_numbers(
    run_id: str, pass_1: float, wrong: int, hidden_only: int
) -> None:
    """Pins the numbers of the committed official runs (they never change)."""
    run = m.load_run(REPO_ROOT / f"lab/evals/results/{run_id}.jsonl")
    stats = m.problem_stats(run.records)
    assert not run.is_partial
    measured = m.pass_at_k_mean(stats, 1)
    assert measured is not None and round(measured, 3) == pass_1
    assert m.pass_at_k_mean(stats, 10) == 1.0
    failures = m.failure_breakdown(run.records)
    assert (failures.wrong, failures.hidden_only) == (wrong, hidden_only)
