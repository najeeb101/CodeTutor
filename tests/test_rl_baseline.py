"""The HF batching and the baseline report (Week 6 Step 3). No GPU: a fake generator."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from codetutor.evals.metrics import RunData
from codetutor.evals.records import EvalRecord, ModelReply
from codetutor.evals.run import RunConfig, RunMeta
from codetutor.grader import GradeResult, GradeStatus
from codetutor.problems import Problem, load_all
from codetutor.rl.baseline import NamedRun, render_report
from codetutor.rl.hf import BatchedResponder, BatchRequestError


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    return load_all()


def _reply(text: str) -> ModelReply:
    return ModelReply(text=text)


def test_all_samples_of_a_problem_come_from_one_batch(bank: list[Problem]) -> None:
    calls: list[int] = []

    def generate(messages: list[dict[str, str]], n: int) -> list[ModelReply]:
        calls.append(n)
        return [_reply(f"batch{len(calls)}-{i}") for i in range(n)]

    responder = BatchedResponder(generate, samples=3)
    first, second = bank[0], bank[1]
    texts = [responder(first, [], i).text for i in range(3)]
    assert texts == ["batch1-0", "batch1-1", "batch1-2"] and calls == [3]
    assert responder(second, [], 0).text == "batch2-0"  # the next problem: a new batch
    assert calls == [3, 3]


def test_a_resume_asks_only_for_the_missing_positions(bank: list[Problem]) -> None:
    responder = BatchedResponder(lambda m, n: [_reply(str(i)) for i in range(n)], samples=10)
    assert [responder(bank[0], [], i).text for i in (4, 5, 9)] == ["4", "5", "9"]


def test_a_bad_position_is_refused(bank: list[Problem]) -> None:
    responder = BatchedResponder(lambda m, n: [_reply("x")] * n, samples=2)
    with pytest.raises(BatchRequestError, match="sample 2 of a batch of 2"):
        responder(bank[0], [], 2)
    with pytest.raises(BatchRequestError, match="seed_base: 0"):
        responder(bank[0], [], None)


# --- the report ---


def _record(problem: Problem, index: int, accepted: bool, reward: float) -> EvalRecord:
    result = GradeResult(
        problem_id=problem.id,
        problem_version=problem.version,
        status=GradeStatus.ACCEPTED if accepted else GradeStatus.WRONG_ANSWER,
        passed=10 if accepted else int(reward * 10),
        total=10,
        tests=[],
        reward=reward,
        stdout="",
        duration_ms=1.0,
        grader_version="test",
    )
    return EvalRecord(
        run_id="t",
        model="hf/x",
        temperature=0.8,
        prompt_version="1",
        problem_id=problem.id,
        problem_version=problem.version,
        sample_index=index,
        reply=_reply(""),
        code="",
        extract_method="python_block",
        result=result,
        created_at=datetime(2026, 10, 7, tzinfo=UTC),
    )


def _run(bank: list[Problem], label: str, passes) -> NamedRun:  # type: ignore[no-untyped-def]
    records = [
        _record(p, i, ok, 1.0 if ok else 0.5)
        for p in bank
        for i in range(10)
        for ok in [passes(p, i)]
    ]
    config = RunConfig(
        run_id="t", model="hf/x", samples=10, temperature=0.8, max_tokens=8, seed_base=0
    )
    meta = RunMeta(
        config=config,
        prompt_version="1",
        grader_version="test",
        problem_versions={p.id: p.version for p in bank},
        model_details={"dtype": "bfloat16"},
        git_commit="abc1234",
        git_dirty=False,
        started_at=datetime(2026, 10, 7, tzinfo=UTC),
    )
    return NamedRun(label, RunData(meta=meta, records=records))


def test_the_report_is_byte_identical_and_covers_every_fold(bank: list[Problem]) -> None:
    run = _run(bank, "toy", lambda p, i: p.module == 1 or i < 3)  # module 1 solved; rest mixed
    first = render_report([run], bank, run)
    assert first == render_report([run], bank, run)
    for fold in ("a", "b", "c", "d"):
        assert f"| {fold} |" in first
    assert "held out" in first and "train" in first
    assert "None" not in first


def test_the_report_counts_flat_and_mixed_groups(bank: list[Problem]) -> None:
    module1 = {p.id for p in bank if p.module == 1}
    run = _run(bank, "toy", lambda p, i: p.id in module1)  # module 1 always passes, rest never
    text = render_report([run], bank)
    assert "100% / 100%" in text  # every group is all-equal
    assert "0 of 33 problems" in text and "None." in text
    mixed = _run(bank, "toy", lambda p, i: i < 3)
    assert "33 of 33 problems" in render_report([mixed], bank)
