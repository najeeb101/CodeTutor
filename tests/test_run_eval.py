"""Tests for the run harness, offline: fake models, real grading in the subprocess sandbox."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from codetutor.evals import (
    ModelConfigError,
    ModelError,
    ModelReply,
    QuotaExhaustedError,
    read_records,
)
from codetutor.evals.fake_models import oracle
from codetutor.evals.run import (
    REPO_ROOT,
    RunConfig,
    RunMeta,
    RunMismatchError,
    load_run_config,
    make_responder,
    meta_path_for,
    run_eval,
)
from codetutor.grader import SubprocessSandbox
from codetutor.problems import Problem, get_problem

PROBLEM_IDS = ["cs1.loops.fizzbuzz", "cs1.strings.compress", "cs1.lists.second_largest"]
CONFIG = RunConfig(
    run_id="test-run",
    model="fake/oracle",
    samples=2,
    temperature=0.8,
    max_tokens=256,
    seed_base=100,
    sandbox="subprocess",
)


class Scripted:
    """A fake model that answers with the reference solution, but raises chosen errors.

    `errors` maps a call number (1, 2, ...) to the exception that call raises.
    """

    def __init__(self, errors: dict[int, Exception] | None = None) -> None:
        self.errors = errors or {}
        self.calls: list[tuple[str, int | None]] = []

    def __call__(
        self, problem: Problem, messages: list[dict[str, str]], seed: int | None
    ) -> ModelReply:
        self.calls.append((problem.id, seed))
        error = self.errors.get(len(self.calls))
        if error is not None:
            raise error
        return oracle(problem)


@pytest.fixture(scope="module")
def problems() -> list[Problem]:
    return [get_problem(problem_id) for problem_id in PROBLEM_IDS]


@pytest.fixture
def results(tmp_path: Path) -> Path:
    return tmp_path / "test-run.jsonl"


def _run(problems: list[Problem], results: Path, model: Scripted, config: RunConfig = CONFIG):
    return run_eval(config, problems, model, SubprocessSandbox(), results)


def _saved(results: Path) -> Counter[tuple[str, int]]:
    """How many times each (problem_id, sample_index) is in the file (must be 1 each)."""
    return Counter((record.problem_id, record.sample_index) for record in read_records(results))


def test_full_run_saves_every_answer_and_the_meta(problems: list[Problem], results: Path) -> None:
    summary = _run(problems, results, Scripted())
    assert (summary.added, summary.missing, summary.stop_reason) == (6, 0, None)
    records = read_records(results)
    assert set(_saved(results)) == {(pid, i) for pid in PROBLEM_IDS for i in range(2)}
    assert {record.seed for record in records} == {100, 101}
    assert {record.run_id for record in records} == {"test-run"}
    assert all(record.passed for record in records)
    hidden = [test for record in records for test in record.result.tests if test.hidden]
    assert hidden and all(test.revealed for test in hidden)  # reveal_hidden=True, as the brief asks
    meta = RunMeta.model_validate_json(meta_path_for(results).read_text())
    assert meta.config == CONFIG
    assert meta.problem_versions == {problem.id: problem.version for problem in problems}


def test_second_run_asks_nothing(problems: list[Problem], results: Path) -> None:
    _run(problems, results, Scripted())
    again = Scripted()
    summary = _run(problems, results, again)
    assert again.calls == []
    assert (summary.already_done, summary.added) == (6, 0)
    assert len(read_records(results)) == 6


def test_quota_stop_keeps_answers_and_a_rerun_fills_the_rest(
    problems: list[Problem], results: Path
) -> None:
    summary = _run(problems, results, Scripted({4: QuotaExhaustedError("quota used up")}))
    assert "quota" in (summary.stop_reason or "")
    assert (summary.added, summary.missing) == (3, 3)
    rest = Scripted()
    summary = _run(problems, results, rest)
    assert len(rest.calls) == 3
    assert summary.missing == 0
    assert set(_saved(results).values()) == {1}  # no duplicates


def test_failed_call_is_not_graded_and_a_rerun_fills_it(
    problems: list[Problem], results: Path
) -> None:
    summary = _run(problems, results, Scripted({2: ModelError("server error")}))
    assert (summary.added, summary.missing, len(summary.failed_calls)) == (5, 1, 1)
    assert (PROBLEM_IDS[0], 1) not in _saved(results)  # call 2 = first problem, sample 1
    rest = Scripted()
    _run(problems, results, rest)
    assert rest.calls == [(PROBLEM_IDS[0], 101)]


def test_many_failures_in_a_row_stop_the_run(problems: list[Problem], results: Path) -> None:
    model = Scripted({number: ModelError("down") for number in range(1, 7)})
    summary = _run(problems, results, model)
    assert "in a row" in (summary.stop_reason or "")
    assert (len(model.calls), summary.added) == (5, 0)


def test_config_error_stops_at_once_and_raises(problems: list[Problem], results: Path) -> None:
    model = Scripted({1: ModelConfigError("wrong key")})
    with pytest.raises(ModelConfigError):
        _run(problems, results, model)
    assert len(model.calls) == 1
    assert not results.exists() or read_records(results) == []


def test_resume_with_other_settings_is_refused(problems: list[Problem], results: Path) -> None:
    _run(problems, results, Scripted())
    other = CONFIG.model_copy(update={"temperature": 0.2})
    with pytest.raises(RunMismatchError, match="config"):
        _run(problems, results, Scripted(), other)
    assert len(read_records(results)) == 6


def test_shipped_configs_load() -> None:
    paths = sorted((REPO_ROOT / "lab" / "evals" / "configs").glob("*.yaml"))
    assert len(paths) >= 2
    for path in paths:
        config = load_run_config(path)
        assert config.sandbox == "docker", path.name  # official runs grade model code in Docker


def test_config_typos_are_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "run_id: x\nmodel: fake/oracle\nsamples: 1\ntemperature: 0\nmax_tokens: 9\nsampels: 5\n"
    )
    with pytest.raises(ValidationError):
        load_run_config(path)


def test_make_responder_rejects_unknown_fake_models() -> None:
    with pytest.raises(ValueError, match="unknown fake model"):
        make_responder(CONFIG.model_copy(update={"model": "fake/nobody"}))
