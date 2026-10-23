"""The fold report and the training-problem filter (Week 6 Step 5). No GPU."""

from __future__ import annotations

import pytest

from codetutor.problems import Problem, load_all
from codetutor.rl.after import (
    FoldRun,
    hardcoded_answers,
    held_out_changes,
    paired,
    pass_rates,
    render_folds_report,
    render_report,
)
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


def _fold_run(bank: list[Problem], name: str, fold: str, seed: int, after_ok) -> FoldRun:  # type: ignore[no-untyped-def]
    before = _run(bank, "before", lambda p, i: i < 3)
    after = _run(bank, "after (GRPO)", after_ok)
    return FoldRun(name, fold, seed, before, after)


def test_held_out_changes_only_use_the_folds_held_out_problems(bank: list[Problem]) -> None:
    run = _fold_run(bank, "c", "c", 0, lambda p, i: i < 6)
    changes = held_out_changes(run, bank)
    assert len(changes) == 8  # fold c holds out modules 3 and 7
    assert all(after == pytest.approx(0.6) for _, after in changes.values())


def test_folds_report_pools_each_problem_once_and_ignores_the_second_seed(
    bank: list[Problem],
) -> None:
    runs = [
        _fold_run(bank, name, fold, 0, lambda p, i: i < 6)
        for name, fold in [("a", "a"), ("b", "b"), ("c", "c"), ("d", "d")]
    ]
    runs.append(_fold_run(bank, "c-s1", "c", 1, lambda p, i: i < 5))
    report = render_folds_report(runs, bank)
    assert report == render_folds_report(runs, bank)  # byte-identical
    pooled = report.split("## 2.")[1].split("## 3.")[0]
    assert f"| {len(bank)} |" in pooled  # 33 problems, not 33 + 8 from the second seed
    assert "+0.30" in pooled and "None" not in report


def test_unknown_fold_name_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown fold"):
        TrainConfig(run_id="x", fold="z", seed=1)


def _load_script():
    """Import scripts/rl_after.py (scripts is not a package)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "rl_after.py"
    spec = importlib.util.spec_from_file_location("rl_after_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_all_skips_a_missing_second_seed_but_not_a_missing_fold(monkeypatch) -> None:
    script = _load_script()
    present = {"a", "b", "c", "d"}
    monkeypatch.setattr(script, "missing_files", lambda n: [] if n in present else [f"x/{n}"])
    names, missing = script.runs_for_report_all()
    assert names == ["a", "b", "c", "d"] and missing == []
    present.discard("b")
    names, missing = script.runs_for_report_all()
    assert "b" in names and missing == ["x/b"]


def test_folds_report_says_when_no_second_seed_was_run(bank: list[Problem]) -> None:
    runs = [_fold_run(bank, n, n, 0, lambda p, i: i < 6) for n in "abcd"]
    report = render_folds_report(runs, bank)
    assert "No second seed was run" in report
    runs.append(_fold_run(bank, "c-s1", "c", 1, lambda p, i: i < 5))
    assert "No second seed was run" not in render_folds_report(runs, bank)
