"""The fold report and the training-problem filter (Week 6 Step 5). No GPU."""

from __future__ import annotations

import pytest

from codetutor.problems import Problem, load_all
from codetutor.rl.after import hardcoded_answers, paired, pass_rates, render_report
from codetutor.rl.train import TrainConfig, mixed_problem_ids
from test_rl_baseline import _record, _run  # the same fake-run builders

META = {
    "config": {
        "lora_rank": 16,
        "steps": 100,
        "prompts_per_step": 4,
        "num_generations": 8,
        "reward_mode": "partial",
        "learning_rate": 1e-5,
        "seed": 0,
    },
    "train_problems": ["a", "b"],
}


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    return load_all()


def _steps() -> list[dict]:
    return [
        {"step": i, "reward": 0.5, "flat_group": 0.0, "seconds": 70.0, "peak_vram_gib": 4.9}
        for i in range(1, 21)
    ]


def test_mixed_problem_ids_ignore_flat_and_held_out_problems(bank: list[Problem]) -> None:
    a, b, c = bank[0], bank[1], bank[2]
    records = [_record(a, i, i < 3, 1.0 if i < 3 else 0.5) for i in range(10)]  # mixed
    records += [_record(b, i, True, 1.0) for i in range(10)]  # all equal
    records += [_record(c, i, i < 3, 1.0 if i < 3 else 0.5) for i in range(10)]  # mixed, held out
    assert mixed_problem_ids(records, [a.id, b.id]) == [a.id]


def test_config_checks_the_group_arithmetic() -> None:
    config = TrainConfig(run_id="x", prompts_per_step=4)
    assert config.num_generations * config.prompts_per_step % config.micro_batch == 0
    with pytest.raises(ValueError, match="multiple of micro_batch"):
        TrainConfig(run_id="x", num_generations=6, micro_batch=4, prompts_per_step=1)


def test_paired_difference_sign_and_counts() -> None:
    result = paired({"p": 0.2, "q": 0.5, "r": 0.5}, {"p": 0.6, "q": 0.5, "r": 0.3})
    assert (result["better"], result["worse"], result["same"]) == (1, 1, 1)
    assert result["mean"] == pytest.approx(0.2 / 3)
    assert paired({}, {"p": 1.0})["mean"] is None


def test_the_report_shows_the_gain_and_is_byte_identical(bank: list[Problem]) -> None:
    before = _run(bank, "before", lambda p, i: i < 3)
    after = _run(bank, "after (GRPO)", lambda p, i: i < 6)
    first = render_report("c", before, after, bank, _steps(), META)
    assert first == render_report("c", before, after, bank, _steps(), META)
    assert "+0.30" in first  # pass@1 0.3 -> 0.6 on every problem
    assert "0 / 0 / 8" not in first and "8 / 0 / 0" in first  # 8 held-out problems, all better
    assert "None" not in first
    assert pass_rates(before.data.records)[bank[0].id] == pytest.approx(0.3)


def test_hardcoding_check_finds_a_written_out_result(bank: list[Problem]) -> None:
    problem = next(p for p in bank if p.id == "cs1.loops.fizzbuzz")
    visible = next(t for t in problem.tests if not t.hidden)
    honest = _record(problem, 0, True, 1.0).model_copy(
        update={"code": "def fizzbuzz(n):\n    return []"}
    )
    cheat = _record(problem, 1, True, 1.0).model_copy(
        update={"code": f"def fizzbuzz(n):\n    return {visible.expected!r}"}
    )
    assert hardcoded_answers([honest, cheat], {problem.id: problem}) == [cheat]
