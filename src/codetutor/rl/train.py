"""GRPO training (Week 6 Steps 4-5): the loop, its cost, and the real run.

One step = `prompts_per_step` prompts, 8 answers each from the model, every answer graded by the
real grader (`TrlReward`), one update of a LoRA adapter. Step 4 ran it with 1 prompt per step to
prove the loop and measure its cost; Step 5 trains for real (4 prompts per step) and tests the
result on held-out problems.

torch, trl and peft are imported inside the functions that need them (like `hf.py`), so the
pure helpers here (config, step log, summary) are tested without a GPU.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from codetutor.evals.records import EvalRecord
from codetutor.problems import Problem
from codetutor.rl.dataset import FOLDS, RL_DIR, TRAIN_FILE, load_rows
from codetutor.rl.env import DEFAULT_MODEL
from codetutor.rl.reward import RewardConfig, TrlReward

SCRATCH_DIR = Path(__file__).resolve().parents[3] / "lab" / "rl" / "scratch"
STEP_LOG = "steps.jsonl"
META_FILE = "meta.json"


class TrainConfig(BaseModel):
    """Every setting of a training run (saved next to the log)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    fold: str = "a"
    model: str = DEFAULT_MODEL
    reward_mode: Literal["partial", "all_or_nothing"] = "partial"
    steps: int = Field(default=30, ge=1)
    num_generations: int = Field(default=8, ge=2)  # answers per prompt = the GRPO group
    prompts_per_step: int = Field(default=1, ge=1)  # prompts (groups) per optimizer step
    micro_batch: int = Field(default=4, ge=1)  # answers per forward/backward pass (memory only)
    save_steps: int | None = Field(default=None, ge=1)  # checkpoint every N steps (None: never)
    train_problems: tuple[str, ...] | None = None  # None = every training problem of the fold
    max_completion_length: int = Field(default=512, ge=16)
    temperature: float = Field(default=0.8, gt=0)  # the same as the baseline
    learning_rate: float = Field(default=1e-5, gt=0)  # LoRA needs a larger rate than full tuning
    lora_rank: int = Field(default=16, ge=1)
    reward_workers: int = Field(default=8, ge=1)
    seed: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.num_generations * self.prompts_per_step % self.micro_batch:
            raise ValueError("num_generations * prompts_per_step must be a multiple of micro_batch")
        if self.fold not in FOLDS:
            names = ", ".join(sorted(FOLDS))
            raise ValueError(f"unknown fold {self.fold!r}; choose one of {names}")


def mixed_problem_ids(records: Sequence[EvalRecord], train_ids: Sequence[str]) -> list[str]:
    """The training problems whose baseline answers did not all get the same reward.

    An all-equal group has advantage 0 for every answer, so training on that prompt changes
    nothing. Only training-side records are read: held-out answers never choose anything.
    """
    rewards: dict[str, set[float]] = {pid: set() for pid in train_ids}
    for record in records:
        if record.problem_id in rewards:
            rewards[record.problem_id].add(record.result.reward)
    return sorted(pid for pid, values in rewards.items() if len(values) > 1)


def run_dir(config: TrainConfig, base: Path = SCRATCH_DIR) -> Path:
    """Where this run's log, meta and adapter go (scratch: not committed)."""
    return base / config.run_id


def train_file(config: TrainConfig, rl_dir: Path = RL_DIR) -> Path:
    """The prompts to train on: the fold's training side (never the held-out modules)."""
    return rl_dir / f"fold-{config.fold}" / TRAIN_FILE


def step_record(
    step: int, logs: Mapping[str, Any], seconds: float, grade_seconds: float, peak_vram_gib: float
) -> dict[str, Any]:
    """One line of the step log: the numbers we report, plus everything TRL logged.

    `model_seconds` is the step minus the time spent grading: generating the answers and
    updating the adapter together (TRL does not give them apart without patching it).
    """
    return {
        "step": step,
        "loss": logs.get("loss"),
        "reward": logs.get("reward"),
        "reward_std": logs.get("reward_std"),
        "flat_group": logs.get("frac_reward_zero_std"),  # 1.0 = every answer got the same reward
        "clipped_share": logs.get("completions/clipped_ratio"),  # answers cut off at the limit
        "mean_length": logs.get("completions/mean_length"),
        "seconds": round(seconds, 2),
        "grade_seconds": round(grade_seconds, 2),
        "model_seconds": round(seconds - grade_seconds, 2),
        "peak_vram_gib": round(peak_vram_gib, 3),
        "trl_logs": dict(logs),
    }


@dataclass(frozen=True)
class RunStats:
    """What a finished run looked like, for comparing reward modes."""

    steps: int
    flat_share: float  # share of steps whose group was all-equal (nothing to learn)
    mean_reward: float
    mean_seconds: float
    peak_vram_gib: float


def summarize(lines: list[dict[str, Any]]) -> RunStats:
    """Fold a step log into the numbers the reward-mode decision needs."""
    if not lines:
        raise ValueError("the step log is empty")
    return RunStats(
        steps=len(lines),
        flat_share=mean(float(line["flat_group"] or 0.0) for line in lines),
        mean_reward=mean(float(line["reward"] or 0.0) for line in lines),
        mean_seconds=mean(line["seconds"] for line in lines),
        peak_vram_gib=max(line["peak_vram_gib"] for line in lines),
    )


def read_step_log(path: Path) -> list[dict[str, Any]]:
    """Read a `steps.jsonl` back."""
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def prefer_mode(partial: RunStats, all_or_nothing: RunStats) -> str:
    """The reward mode to use for the real runs: "partial" or "all_or_nothing".

    The rule was written before the runs (plan, Step 4): prefer the mode whose groups are
    all-equal less often, because an all-equal group teaches nothing; on a tie, "partial".
    """
    # TODO(najeeb): write the rule above with the two `flat_share` numbers. Hint: a tie is
    # `==`; and think about what a "tie" means when each run has only ~30 steps (is 0.20 vs
    # 0.23 a real difference?). Keep it to a few lines; the docs will say how little 30 steps prove.
    raise NotImplementedError("prefer_mode: Najeeb's TODO")


def build_trainer(config: TrainConfig, bank: list[Problem], out_dir: Path) -> tuple[Any, TrlReward]:
    """The `GRPOTrainer` for `config` and its reward object (read its counters after a step)."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import TrainerCallback
    from trl import GRPOConfig, GRPOTrainer

    rows = load_rows(train_file(config))
    if config.train_problems is not None:
        rows = [r for r in rows if r.problem_id in config.train_problems]
        if not rows:
            raise ValueError("train_problems matches no training row of this fold")
    dataset = Dataset.from_list([{"prompt": r.prompt, "problem_id": r.problem_id} for r in rows])
    reward = TrlReward(bank, RewardConfig(mode=config.reward_mode, workers=config.reward_workers))
    args = GRPOConfig(
        output_dir=str(out_dir / "trainer"),
        max_steps=config.steps,
        num_generations=config.num_generations,
        # `prompts_per_step` groups per step, in `micro_batch` pieces: the groups and the update
        # are the same, only less GPU memory is needed at once.
        per_device_train_batch_size=config.micro_batch,
        gradient_accumulation_steps=config.num_generations
        * config.prompts_per_step
        // config.micro_batch,
        max_completion_length=config.max_completion_length,
        temperature=config.temperature,
        learning_rate=config.learning_rate,
        bf16=True,
        seed=config.seed,
        logging_steps=1,
        save_strategy="no" if config.save_steps is None else "steps",
        save_steps=config.save_steps or 500,
        save_total_limit=2,
        report_to="none",
    )
    lora = LoraConfig(
        r=config.lora_rank,
        lora_alpha=2 * config.lora_rank,
        target_modules="all-linear",
        task_type="CAUSAL_LM",
    )

    class StepLog(TrainerCallback):
        """Writes one JSON line per step: TRL's metrics plus time, grading time and VRAM."""

        def __init__(self) -> None:
            self.started = time.perf_counter()
            self.graded_before = 0.0
            self.path = out_dir / STEP_LOG

        def on_train_begin(self, args_, state, control, **kwargs):  # noqa: ANN001, ANN201
            self.started = time.perf_counter()  # the first step must not include the model load
            self.graded_before = reward.counters.seconds
            torch.cuda.reset_peak_memory_stats()

        def on_log(self, args_, state, control, logs=None, **kwargs):  # noqa: ANN001, ANN201
            if not logs or "loss" not in logs:  # the final summary line has no loss
                return
            now = time.perf_counter()
            graded = reward.counters.seconds
            record = step_record(
                state.global_step,
                logs,
                seconds=now - self.started,
                grade_seconds=graded - self.graded_before,
                peak_vram_gib=torch.cuda.max_memory_allocated() / 1024**3,
            )
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
            self.started, self.graded_before = now, graded
            torch.cuda.reset_peak_memory_stats()

    trainer = GRPOTrainer(
        model=config.model,
        reward_funcs=[reward],
        args=args,
        train_dataset=dataset,
        peft_config=lora,
        callbacks=[StepLog()],
    )
    return trainer, reward
