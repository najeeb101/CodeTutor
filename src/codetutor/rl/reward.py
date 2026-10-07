"""The reward for GRPO (Week 6 Step 2): the one grader, seen as a function `answer -> number`.

`reward_for` is `extract_code` + `grade()`, the same path as student submissions and model evals.
`TrlReward` wraps it for TRL's `GRPOTrainer`: a batch of chat completions in, one float per
completion out. It runs in the trainer process and sees the full problems (hidden tests); the
model only ever sees the student-view prompts of Step 1.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from codetutor.evals.extract import extract_code
from codetutor.grader import DockerSandbox, GradeStatus, Sandbox, SubprocessSandbox, grade
from codetutor.problems import Problem

log = logging.getLogger(__name__)


class UnknownProblemError(KeyError):
    """A dataset row names a problem that is not in the bank (a setup mistake)."""


class RewardConfig(BaseModel):
    """How a grade becomes a reward."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # "partial": the grade's reward (passed / total). "all_or_nothing": 1.0 only when every test
    # passes. Chosen in Step 4 from measured within-group variance (docs/ideas.md, is_prime).
    mode: Literal["partial", "all_or_nothing"] = "partial"
    workers: int = Field(default=4, ge=1)  # answers graded at the same time
    sandbox: Literal["docker", "subprocess"] = "docker"  # docker: model code is untrusted


@dataclass(frozen=True)
class RewardResult:
    """One answer's reward and why."""

    reward: float
    status: str  # a GradeStatus value, or "error" when grading itself failed
    passed: int
    total: int
    extract_method: str


def make_sandbox(config: RewardConfig) -> Sandbox:
    """The sandbox the config asks for (Docker raises `SandboxUnavailableError` if it is down)."""
    return DockerSandbox() if config.sandbox == "docker" else SubprocessSandbox()


def reward_for(
    problem: Problem, reply: str, config: RewardConfig, sandbox: Sandbox | None = None
) -> RewardResult:
    """Extract the code from `reply`, grade it, turn the grade into a reward.

    No code, wrong code, a crash or a timeout all come out of `grade()` as reward 0.
    """
    extraction = extract_code(reply, problem.function_name)
    result = grade(problem, extraction.code, reveal_hidden=False, sandbox=sandbox)
    accepted = result.status == GradeStatus.ACCEPTED
    reward = result.reward
    if config.mode == "all_or_nothing":
        reward = 1.0 if accepted else 0.0
    return RewardResult(
        reward, result.status.value, result.passed, result.total, extraction.method.value
    )


@dataclass
class RewardCounters:
    """What the reward function did so far (for the training log)."""

    answers: int = 0
    accepted: int = 0
    errors: int = 0  # grading itself failed (not the model's fault): scored 0.0
    seconds: float = 0.0
    reward_sum: float = 0.0


class TrlReward:
    """A reward function for `GRPOTrainer(reward_funcs=...)`.

    Called as `reward(prompts=..., completions=..., problem_id=[...])`; each completion is a
    chat message list (`[{"role": "assistant", "content": text}]`) or a plain string. Returns one
    float per completion, in order. It never raises for one bad answer: a failure inside the
    grader is logged, counted in `counters.errors` and scored 0.0, so a broken sandbox shows up
    as an error count instead of killing a long training run.
    """

    __name__ = "grader_reward"  # TRL logs the reward under the function's name

    def __init__(self, bank: Sequence[Problem], config: RewardConfig | None = None) -> None:
        self.config = config or RewardConfig()
        self.problems: Mapping[str, Problem] = {p.id: p for p in bank}
        self.sandbox = make_sandbox(self.config)
        self.counters = RewardCounters()
        self._lock = threading.Lock()

    def __call__(
        self, prompts: Sequence[Any] = (), completions: Sequence[Any] = (), **columns: Any
    ) -> list[float]:
        ids = columns.get("problem_id")
        if ids is None or len(ids) != len(completions):
            raise ValueError("the dataset needs a `problem_id` column, one per completion")
        unknown = sorted({i for i in ids if i not in self.problems})
        if unknown:
            raise UnknownProblemError(f"problems not in the bank: {', '.join(unknown)}")
        start = time.perf_counter()
        jobs = [(self.problems[i], _reply_text(c)) for i, c in zip(ids, completions, strict=True)]
        with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
            results = list(pool.map(self._grade_one, jobs))
        with self._lock:
            self.counters.answers += len(results)
            self.counters.accepted += sum(r.status == GradeStatus.ACCEPTED.value for r in results)
            self.counters.errors += sum(r.status == "error" for r in results)
            self.counters.seconds += time.perf_counter() - start
            self.counters.reward_sum += sum(r.reward for r in results)
        return [r.reward for r in results]

    def _grade_one(self, job: tuple[Problem, str]) -> RewardResult:
        problem, reply = job
        try:
            return reward_for(problem, reply, self.config, self.sandbox)
        except Exception:  # one answer must never stop a training run: logged, counted, scored 0.0
            log.exception("grading failed for %s; scored 0.0", problem.id)
            return RewardResult(0.0, "error", 0, 0, "none")


def _reply_text(completion: Any) -> str:
    """The text of one completion: a string, or the last message's content."""
    if isinstance(completion, str):
        return completion
    return str(completion[-1]["content"])


@dataclass(frozen=True)
class GroupStats:
    """How much a batch of GRPO groups can teach."""

    groups: int
    mean_reward: float
    flat_share: float  # share of groups whose rewards are all equal: no signal for that prompt
    mean_spread: float  # mean of (max - min) inside a group


def group_stats(rewards: Sequence[float], group_size: int) -> GroupStats:
    """Cut `rewards` into consecutive groups of `group_size` (one prompt's answers each)."""
    if group_size < 1 or len(rewards) % group_size:
        raise ValueError(f"{len(rewards)} rewards do not split into groups of {group_size}")
    groups = [rewards[i : i + group_size] for i in range(0, len(rewards), group_size)]
    if not groups:
        return GroupStats(0, 0.0, 0.0, 0.0)
    flat = sum(max(g) == min(g) for g in groups)
    return GroupStats(
        len(groups),
        mean(rewards),
        flat / len(groups),
        mean(max(g) - min(g) for g in groups),
    )
