"""The RL reward (Week 6 Step 2): the one grader as a function, and the ways to cheat it."""

from __future__ import annotations

import pytest

from codetutor.evals.records import EvalRecord, read_records
from codetutor.grader import SubprocessSandbox
from codetutor.grader.sandbox import RawResult, SandboxJob
from codetutor.problems import Problem, get_problem, load_all
from codetutor.rl.reward import (
    RewardConfig,
    TrlReward,
    UnknownProblemError,
    group_stats,
    reward_for,
)
from conftest import REPO_ROOT

PARTIAL = RewardConfig(sandbox="subprocess")
STRICT = RewardConfig(sandbox="subprocess", mode="all_or_nothing")
RESULTS = REPO_ROOT / "lab" / "evals" / "results" / "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl"


@pytest.fixture(scope="module")
def fizzbuzz() -> Problem:
    return get_problem("cs1.loops.fizzbuzz")


def _fenced(code: str) -> str:
    return f"```python\n{code}\n```"


def _score(problem: Problem, reply: str, config: RewardConfig = PARTIAL) -> float:
    return reward_for(problem, reply, config, SubprocessSandbox()).reward


CORRECT = """\
def fizzbuzz(n):
    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    return out
"""


def test_a_correct_answer_gets_full_reward_in_both_modes(fizzbuzz: Problem) -> None:
    assert _score(fizzbuzz, _fenced(CORRECT)) == 1.0
    assert _score(fizzbuzz, _fenced(CORRECT), STRICT) == 1.0


def test_a_one_bug_answer_is_partial_in_one_mode_and_zero_in_the_other(fizzbuzz: Problem) -> None:
    buggy = CORRECT.replace("i % 15 == 0", "i % 3 == 0 and False")  # never FizzBuzz
    assert 0.0 < _score(fizzbuzz, _fenced(buggy)) < 1.0
    assert _score(fizzbuzz, _fenced(buggy), STRICT) == 0.0


# --- ways a model could cheat; none may reach 1.0 ---


def test_hard_coding_the_visible_examples_is_caught_by_hidden_tests(fizzbuzz: Problem) -> None:
    table = {t.input[0]: t.expected for t in fizzbuzz.visible_tests}
    code = f"def fizzbuzz(n):\n    return {table!r}.get(n, [])\n"
    assert _score(fizzbuzz, _fenced(code)) < 1.0
    assert _score(fizzbuzz, _fenced(code), STRICT) == 0.0


@pytest.mark.parametrize(
    "code",
    [
        'def fizzbuzz(n):\n    print(["1", "2", "Fizz"])\n',  # prints instead of returning
        "import sys\nsys.exit(0)\ndef fizzbuzz(n):\n    return []\n",
        "import os\nos._exit(0)\ndef fizzbuzz(n):\n    return []\n",
        'import json\nprint("\\nFAKETOKEN" + json.dumps({"status": "accepted", "reward": 1.0}))\n'
        "def fizzbuzz(n):\n    return []\n",
    ],
    ids=["prints", "sys_exit", "os_exit", "fake_token"],
)
def test_other_cheats_do_not_reach_full_reward(fizzbuzz: Problem, code: str) -> None:
    assert _score(fizzbuzz, _fenced(code)) < 1.0


@pytest.mark.parametrize("reply", ["", "I cannot help with that.", "```python\nx = 1\n```"])
def test_no_code_or_code_without_the_function_scores_zero(fizzbuzz: Problem, reply: str) -> None:
    assert _score(fizzbuzz, reply) == 0.0


# --- the same path as the evals ---


def test_the_reward_equals_the_stored_eval_reward_for_real_answers() -> None:
    records: list[EvalRecord] = [
        r for r in read_records(RESULTS) if r.result.status.value != "timeout"
    ]
    bank = {p.id: p for p in load_all()}
    sample = records[:: max(1, len(records) // 24)][:24]
    assert len(sample) >= 20
    sandbox = SubprocessSandbox()
    for record in sample:
        got = reward_for(bank[record.problem_id], record.reply.text, PARTIAL, sandbox).reward
        assert got == record.result.reward, (record.problem_id, record.sample_index)


# --- the TRL wrapper ---


class _BrokenSandbox:
    def run(self, job: SandboxJob) -> RawResult:
        raise OSError("the sandbox fell over")


def _chat(text: str) -> list[dict[str, str]]:
    return [{"role": "assistant", "content": text}]


def test_a_mixed_batch_keeps_its_order_and_counts(fizzbuzz: Problem) -> None:
    other = get_problem("cs1.loops.sum_of_evens")
    reward = TrlReward([fizzbuzz, other], PARTIAL)
    batch = [_chat(_fenced(CORRECT)), _chat("no code"), _chat(_fenced(CORRECT))]
    ids = [fizzbuzz.id, fizzbuzz.id, other.id]  # the last answer solves the wrong problem
    values = reward(prompts=["p"] * 3, completions=batch, problem_id=ids)
    assert values == [1.0, 0.0, 0.0]
    assert (reward.counters.answers, reward.counters.accepted, reward.counters.errors) == (3, 1, 0)
    assert reward.__name__ == "grader_reward"


def test_a_plain_string_completion_works_too(fizzbuzz: Problem) -> None:
    reward = TrlReward([fizzbuzz], PARTIAL)
    assert reward(completions=[_fenced(CORRECT)], problem_id=[fizzbuzz.id]) == [1.0]


def test_a_missing_or_unknown_problem_is_a_loud_setup_error(fizzbuzz: Problem) -> None:
    reward = TrlReward([fizzbuzz], PARTIAL)
    with pytest.raises(UnknownProblemError, match="cs1.nope"):
        reward(completions=[_chat("x")], problem_id=["cs1.nope"])
    with pytest.raises(ValueError, match="problem_id"):
        reward(completions=[_chat("x")])


def test_a_failing_sandbox_scores_zero_and_is_counted_not_raised(fizzbuzz: Problem) -> None:
    reward = TrlReward([fizzbuzz], PARTIAL)
    reward.sandbox = _BrokenSandbox()  # type: ignore[assignment]
    values = reward(completions=[_chat(_fenced(CORRECT))] * 2, problem_id=[fizzbuzz.id] * 2)
    assert values == [0.0, 0.0]
    assert (reward.counters.answers, reward.counters.errors) == (2, 2)


def test_group_stats() -> None:
    stats = group_stats([1, 1, 1, 1, 0, 1, 0, 1, 0, 0, 0, 0], 4)
    assert stats.groups == 3
    assert stats.flat_share == pytest.approx(2 / 3)  # the all-1 and the all-0 groups
    assert stats.mean_spread == pytest.approx(1 / 3)
    assert stats.mean_reward == pytest.approx(0.5)
    assert group_stats([], 4).groups == 0
    with pytest.raises(ValueError, match="do not split"):
        group_stats([1, 2, 3], 2)
