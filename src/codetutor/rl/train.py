"""A GRPO smoke run (Week 6 Step 4): does the whole training loop run, and what does it cost?

One step = one prompt, 8 answers from the model, each graded by the real grader (`TrlReward`),
one small update of a LoRA adapter. The point is the loop and its cost, not a better model:
a few dozen steps cannot show a reliable gain.

torch, trl and peft are imported inside the functions that need them (like `hf.py`), so the
pure helpers here (config, step log, summary) are tested without a GPU.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from codetutor.problems import Problem
from codetutor.rl.dataset import FOLDS, RL_DIR, TRAIN_FILE, load_rows
from codetutor.rl.env import DEFAULT_MODEL
from codetutor.rl.reward import RewardConfig, TrlReward

SCRATCH_DIR = Path(__file__).resolve().parents[3] / "lab" / "rl" / "scratch"
STEP_LOG = "steps.jsonl"
META_FILE = "meta.json"


class SmokeConfig(BaseModel):
    """Every setting of a smoke run (saved next to the log)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    fold: str = "a"
    model: str = DEFAULT_MODEL
    reward_mode: Literal["partial", "all_or_nothing"] = "partial"
    steps: int = Field(default=30, ge=1)
    num_generations: int = Field(default=8, ge=2)  # answers per prompt = the GRPO group
    micro_batch: int = Field(default=4, ge=1)  # answers per forward/backward pass (memory only)
    max_completion_length: int = Field(default=512, ge=16)
    temperature: float = Field(default=0.8, gt=0)  # the same as the baseline
    learning_rate: float = Field(default=1e-5, gt=0)  # LoRA needs a larger rate than full tuning
    lora_rank: int = Field(default=16, ge=1)
    reward_workers: int = Field(default=8, ge=1)
    seed: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.num_generations % self.micro_batch:
            raise ValueError("num_generations must be a multiple of micro_batch")
        if self.fold not in FOLDS:
            names = ", ".join(sorted(FOLDS))
            raise ValueError(f"unknown fold {self.fold!r}; choose one of {names}")


def run_dir(config: SmokeConfig, base: Path = SCRATCH_DIR) -> Path:
    """Where this run's log, meta and adapter go (scratch: not committed)."""
    return base / config.run_id


def train_file(config: SmokeConfig, rl_dir: Path = RL_DIR) -> Path:
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


def build_trainer(config: SmokeConfig, bank: list[Problem], out_dir: Path) -> tuple[Any, TrlReward]:
    """The `GRPOTrainer` for `config` and its reward object (read its counters after a step)."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import TrainerCallback
    from trl import GRPOConfig, GRPOTrainer

    rows = load_rows(train_file(config))
    dataset = Dataset.from_list([{"prompt": r.prompt, "problem_id": r.problem_id} for r in rows])
    reward = TrlReward(bank, RewardConfig(mode=config.reward_mode, workers=config.reward_workers))
    args = GRPOConfig(
        output_dir=str(out_dir / "trainer"),
        max_steps=config.steps,
        num_generations=config.num_generations,
        # One prompt's answers per step, in `micro_batch` pieces: the group and the update are the
        # same, only less GPU memory is needed at once.
        per_device_train_batch_size=config.micro_batch,
        gradient_accumulation_steps=config.num_generations // config.micro_batch,
        max_completion_length=config.max_completion_length,
        temperature=config.temperature,
        learning_rate=config.learning_rate,
        bf16=True,
        seed=config.seed,
        logging_steps=1,
        save_strategy="no",
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
