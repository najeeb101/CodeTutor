"""Check and time the RL reward on the stored Week 2 answers (Week 6 Step 2).

Usage:
    uv run python scripts/rl_reward_bench.py            # needs Docker (the real sandbox)

1. Consistency: re-score every stored answer of both models with `reward_for` and compare with
   the reward saved in the results file (differences are listed; expected: only timeouts).
2. Throughput: grade the same 64 answers with Docker at 1, 4 and 8 workers, and with the
   subprocess sandbox (trusted fixtures only), answers per second.
3. Signal: for the 1.5B's 10 answers per problem, how many groups have all-equal rewards
   (nothing to learn), under both reward modes.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from codetutor.evals.records import EvalRecord, read_records
from codetutor.grader import DockerSandbox, SandboxUnavailableError, SubprocessSandbox
from codetutor.problems import load_all
from codetutor.rl.reward import RewardConfig, TrlReward, group_stats

RESULTS = Path(__file__).resolve().parents[1] / "lab" / "evals" / "results"
FILES = {
    "1.5B": "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl",
    "7B": "qwen2.5-coder-7b-q4-t0.8-n10.jsonl",
}
SAMPLE = 64


def main() -> int:
    bank = {p.id: p for p in load_all()}
    try:
        docker = DockerSandbox()
    except SandboxUnavailableError as exc:
        print(f"Docker is not available: {exc}", file=sys.stderr)
        return 1
    data = {name: sorted(read_records(RESULTS / f), key=_key) for name, f in FILES.items()}

    print("1. consistency with the stored rewards (Docker, 4 workers)")
    for name, records in data.items():
        rewards = _grade(records, bank, RewardConfig(workers=4), docker)
        bad = [(r, got) for r, got in zip(records, rewards, strict=True) if got != r.result.reward]
        print(f"  {name}: {len(records) - len(bad)} of {len(records)} equal the stored reward")
        for record, got in bad:
            print(
                f"    {record.problem_id} #{record.sample_index}: stored "
                f"{record.result.reward} ({record.result.status.value}), now {got}"
            )

    print(f"2. throughput on {SAMPLE} answers (the 1.5B's, spread over the problems)")
    records = data["1.5B"]
    sample = records[:: len(records) // SAMPLE][:SAMPLE]
    for label, config, sandbox in (
        ("docker, 1 worker ", RewardConfig(workers=1), docker),
        ("docker, 4 workers", RewardConfig(workers=4), docker),
        ("docker, 8 workers", RewardConfig(workers=8), docker),
        ("subprocess, 4    ", RewardConfig(workers=4, sandbox="subprocess"), SubprocessSandbox()),
    ):
        start = time.perf_counter()
        _grade(sample, bank, config, sandbox)
        seconds = time.perf_counter() - start
        print(f"  {label}: {seconds:5.1f} s = {len(sample) / seconds:4.1f} answers/s")

    print("3. groups of 10 answers per problem (the 1.5B): how many give no signal")
    for mode in ("partial", "all_or_nothing"):
        rewards = _grade(records, bank, RewardConfig(mode=mode, workers=4), docker)  # type: ignore[arg-type]
        stats = group_stats(rewards, 10)
        print(
            f"  {mode:<14}: mean reward {stats.mean_reward:.3f}, "
            f"{stats.flat_share:.0%} of {stats.groups} groups all-equal, "
            f"mean spread {stats.mean_spread:.2f}"
        )
    return 0


def _key(record: EvalRecord) -> tuple[str, int]:
    return record.problem_id, record.sample_index


def _grade(records, bank, config, sandbox) -> list[float]:
    reward = TrlReward(list(bank.values()), config)
    reward.sandbox = sandbox
    return reward(
        completions=[r.reply.text for r in records], problem_id=[r.problem_id for r in records]
    )


if __name__ == "__main__":
    sys.exit(main())
