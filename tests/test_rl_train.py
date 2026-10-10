"""The GRPO smoke run's pure parts (Week 6 Step 4): no GPU needed."""

from __future__ import annotations

import json

import pytest

from codetutor.rl.dataset import load_rows
from codetutor.rl.train import (
    SmokeConfig,
    read_step_log,
    run_dir,
    step_record,
    summarize,
    train_file,
)


def test_config_is_frozen_and_checked() -> None:
    config = SmokeConfig(run_id="x")
    assert (config.fold, config.num_generations, config.reward_mode) == ("a", 8, "partial")
    with pytest.raises(ValueError, match="unknown fold"):
        SmokeConfig(run_id="x", fold="z")
    with pytest.raises(ValueError):
        SmokeConfig(run_id="x", reward_mode="half")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SmokeConfig(run_id="x", num_generations=1)  # a group of one has no "better than the rest"


def test_run_dir_is_under_the_base(tmp_path) -> None:
    assert run_dir(SmokeConfig(run_id="r1"), tmp_path) == tmp_path / "r1"


def test_step_record_splits_model_time_from_grading_time() -> None:
    logs = {"loss": 0.1, "reward": 0.5, "reward_std": 0.2, "frac_reward_zero_std": 0.0}
    record = step_record(3, logs, seconds=60.0, grade_seconds=15.5, peak_vram_gib=4.0)
    assert record["model_seconds"] == 44.5
    assert record["flat_group"] == 0.0
    assert record["trl_logs"] == logs
    json.dumps(record)  # must be writable as a log line


def test_summarize_counts_flat_steps() -> None:
    lines = [
        step_record(i, {"loss": 0, "reward": r, "frac_reward_zero_std": f}, 10.0, 2.0, v)
        for i, (r, f, v) in enumerate([(1.0, 1.0, 3.0), (0.5, 0.0, 3.5), (0.25, 0.0, 3.2)])
    ]
    stats = summarize(lines)
    assert stats.steps == 3
    assert stats.flat_share == pytest.approx(1 / 3)
    assert stats.mean_reward == pytest.approx(1.75 / 3)
    assert stats.peak_vram_gib == 3.5
    with pytest.raises(ValueError, match="empty"):
        summarize([])


def test_step_log_round_trip(tmp_path) -> None:
    path = tmp_path / "steps.jsonl"
    record = step_record(1, {"loss": 0.0}, 1.0, 0.5, 1.0)
    path.write_text(json.dumps(record) + "\n\n", encoding="utf-8")
    assert read_step_log(path) == [record]


def test_training_file_holds_only_train_problems_with_the_reward_columns() -> None:
    path = train_file(SmokeConfig(run_id="x"))
    if not path.exists():
        pytest.skip("run `make rl-data` first")
    rows = load_rows(path)
    assert rows and all(r.module not in (1, 5) for r in rows)  # fold a holds out modules 1 + 5
    assert all(r.prompt and r.problem_id for r in rows)
