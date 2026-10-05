"""The offline tutor eval (Week 4 Step 4): situations, the student's prompt, both phases,
resuming, and the report's numbers. Fake models; the subprocess sandbox grades our own code."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from codetutor.evals.clients import ModelError
from codetutor.evals.metrics import bootstrap_mean_ci
from codetutor.evals.records import ModelReply
from codetutor.grader import SubprocessSandbox
from codetutor.problems import Problem
from codetutor.tutor.safety import Situation, build_situations
from codetutor.tutor.service import TutorConfig
from codetutor.tutor.tutor_eval import (
    CONDITIONS,
    STUDENT_PROMPT_VERSION,
    TutorEvalMismatchError,
    TutorEvalSettings,
    build_student_messages,
    hidden_only,
    hint_for,
    make_tutor_hints,
    read_records,
    run_student,
    start_or_check_meta,
)
from codetutor.tutor.tutor_eval_report import condition_stats, fix_rates, render_report
from conftest import BUGGY, SOLUTION, ScriptedModel, valid_problem_data

# Passes the visible tests (n >= 1) but returns -1 for the hidden n = 0 and n = -5.
HIDDEN_ONLY = """def sum_of_evens(n: int) -> int:
    total = 0
    for i in range(2, n + 1, 2):
        total += i
    return total if n > 0 else -1
"""
SOLUTION_LINE = "return sum(range(2, n + 1, 2))"
HINT = "What should the function return when n is 0 or negative?"
SANDBOX = SubprocessSandbox()  # our own code and fake replies made of it
SETTINGS = TutorEvalSettings(student="fake/student", tutor="fake/tutor", samples=2)
# The pinned student prompt (conftest problem, HIDDEN_ONLY, HINT): sha256 of the user message.
PINNED_PROMPT_SHA256 = "7d76d669ca5b90eebca278bb728576f2580fa86d9c16038a8fdf3d815486a4e3"


@pytest.fixture(scope="module")
def situations() -> list[Situation]:
    data = valid_problem_data()
    data["buggy"] = {"off_by_one": BUGGY, "negative_is_minus_one": HIDDEN_ONLY}
    return build_situations([Problem.model_validate(data)], sandbox=SANDBOX)


@pytest.fixture(scope="module")
def situation(situations: list[Situation]) -> Situation:
    [picked] = hidden_only(situations)
    return picked


class HintFollower:
    """A fake student: the solution when the prompt has a hint, else the buggy code again."""

    name = "fake/student"

    def __init__(self) -> None:
        self.seeds: list[int | None] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
    ) -> ModelReply:
        self.seeds.append(seed)
        code = SOLUTION if "A hint from your tutor" in messages[-1]["content"] else HIDDEN_ONLY
        return ModelReply(text=f"```python\n{code}```", prompt_tokens=500)


def _start(path: Path, situations: list[Situation], settings: TutorEvalSettings = SETTINGS):
    return start_or_check_meta(settings, TutorConfig(), situations, path, ask_models=False)


# --- Situations and the prompt ---


def test_only_hidden_only_bugs_are_situations(situations: list[Situation]) -> None:
    picked = hidden_only(situations)
    # off_by_one fails a visible test; the injected copy is a safety-run case, not a student.
    assert [(s.buggy, s.injected) for s in picked] == [("negative_is_minus_one", False)]
    assert any(s.injected for s in situations)


def test_the_student_prompt_is_pinned(situation: Situation) -> None:
    prompt = build_student_messages(situation, HINT)[-1]["content"]
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    assert (STUDENT_PROMPT_VERSION, digest) == ("1", PINNED_PROMPT_SHA256), (
        "the student prompt changed: bump STUDENT_PROMPT_VERSION and update the pinned hash"
    )


def test_the_prompt_shows_what_the_ui_shows_and_no_secrets(situation: Situation) -> None:
    prompt = build_student_messages(situation, HINT)[-1]["content"]
    assert HIDDEN_ONLY.strip() in prompt
    assert "Visible tests: 4 of 4 passed." in prompt
    assert "Hidden tests: 2 of 4 passed" in prompt
    assert f"### A hint from your tutor\n{HINT}" in prompt
    for secret in (SOLUTION_LINE, "sum_of_evens(-5)", "2550", "Hint three."):
        assert secret not in prompt
    without = build_student_messages(situation, None)[-1]["content"]
    assert "A hint from your tutor" not in without


def test_each_condition_gets_its_hint(situation: Situation) -> None:
    tutor = {
        "cs1.loops.sum_of_evens/negative_is_minus_one#1": "tutor one",
        "cs1.loops.sum_of_evens/negative_is_minus_one#2": "tutor two",
    }
    hints = {condition: hint_for(situation, condition, tutor) for condition in CONDITIONS}
    assert hints == {
        "none": None,
        "teacher-1": "Hint one.",
        "tutor-1": "tutor one",
        "teacher-2": "Hint two.",
        "tutor-2": "tutor two",
        "teacher-3": "Hint three.",
    }


# --- The two phases ---


def test_tutor_hints_are_made_once_and_level_2_knows_level_1(
    situation: Situation, tmp_path: Path
) -> None:
    path = tmp_path / "results.jsonl"
    tutor = ScriptedModel("Look at n = 0.", "When n is 0, what does your last line return?")
    summary = make_tutor_hints(
        [situation], tutor, path, session=None, embedder=None, config=TutorConfig()
    )
    hints = read_records(path)
    assert (summary.added, [h["level"] for h in hints]) == (2, [1, 2])
    assert [h["source"] for h in hints] == ["model", "model"]
    assert "Look at n = 0." in tutor.calls[1][-1]["content"]  # "hints you already gave"
    again = make_tutor_hints(
        [situation], ScriptedModel(), path, session=None, embedder=None, config=TutorConfig()
    )
    assert (again.added, again.already_done) == (0, 2)  # no model call (no replies left)


def test_a_hint_that_helps_shows_up_as_paired_help(situation: Situation, tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    _start(path, [situation])
    student = HintFollower()
    summary = run_student([situation], ["none", "teacher-1"], SETTINGS, student, SANDBOX, path)
    assert (summary.added, summary.failed_calls) == (4, [])
    assert student.seeds == [0, 1, 0, 1]  # sample i gets seed i, in every condition
    records = read_records(path)
    assert {(r["condition"], r["status"]) for r in records} == {
        ("none", "wrong_answer"),
        ("teacher-1", "accepted"),
    }
    [none, teacher] = condition_stats(records)
    assert (none.fix_rate, none.help, none.situations, none.answers) == (0.0, None, 1, 2)
    assert (teacher.fix_rate, teacher.help, teacher.better) == (1.0, 1.0, 1)


def test_a_resumed_run_asks_only_for_missing_answers(situation: Situation, tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    _start(path, [situation])
    run_student([situation], ["none"], SETTINGS, HintFollower(), SANDBOX, path)
    student = HintFollower()
    summary = run_student([situation], ["none", "teacher-2"], SETTINGS, student, SANDBOX, path)
    assert (summary.already_done, summary.added, student.seeds) == (2, 2, [0, 1])
    assert len(read_records(path)) == 4


def test_tutor_conditions_need_the_hints_first(situation: Situation, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run make_tutor_hints first"):
        run_student(
            [situation], ["tutor-1"], SETTINGS, HintFollower(), SANDBOX, tmp_path / "results.jsonl"
        )


def test_failed_calls_are_never_graded(situation: Situation, tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    failing = ScriptedModel(*[ModelError("provider error")] * 5)
    many = SETTINGS.model_copy(update={"samples": 5})
    summary = run_student([situation], ["none", "teacher-1"], many, failing, SANDBOX, path)
    assert summary.stop_reason == "5 failed model calls in a row"
    assert (summary.added, len(summary.failed_calls), read_records(path)) == (0, 5, [])


def test_other_settings_are_refused_but_other_conditions_are_not(
    situation: Situation, tmp_path: Path
) -> None:
    path = tmp_path / "results.jsonl"
    _start(path, [situation])
    _start(path, [situation])  # the same settings: fine
    with pytest.raises(TutorEvalMismatchError, match="settings"):
        _start(path, [situation], SETTINGS.model_copy(update={"samples": 3}))


# --- The report ---


def _answer(situation: str, condition: str, index: int, accepted: bool) -> dict[str, Any]:
    return {
        "kind": "answer",
        "situation": situation,
        "condition": condition,
        "sample_index": index,
        "hint": None if condition == "none" else f"hint for {situation}",
        "status": "accepted" if accepted else "wrong_answer",
        "reward": 1.0 if accepted else 0.5,
    }


RECORDS = [
    # a: none 0/2, tutor-1 2/2 (+1.0); b: none 1/2, tutor-1 0/2 (-0.5); c: 2/2 both (0)
    *[_answer("p/a", "none", i, False) for i in range(2)],
    *[_answer("p/a", "tutor-1", i, True) for i in range(2)],
    _answer("p/b", "none", 0, True),
    _answer("p/b", "none", 1, False),
    *[_answer("p/b", "tutor-1", i, False) for i in range(2)],
    *[_answer("p/c", condition, i, True) for condition in ("none", "tutor-1") for i in range(2)],
    {"kind": "hint", "situation": "p/a", "level": 1, "text": "one two three", "source": "model"},
    {"kind": "hint", "situation": "p/b", "level": 1, "text": "a b", "source": "fallback"},
]


def test_fix_rates_are_per_situation_then_averaged() -> None:
    assert fix_rates(RECORDS) == {
        "none": {"p/a": 0.0, "p/b": 0.5, "p/c": 1.0},
        "tutor-1": {"p/a": 1.0, "p/b": 0.0, "p/c": 1.0},
    }
    [none, tutor] = condition_stats(RECORDS)
    assert none.fix_rate == pytest.approx(0.5) and tutor.fix_rate == pytest.approx(2 / 3)
    assert tutor.help == pytest.approx(1 / 6)  # mean of +1.0, -0.5, 0
    assert (tutor.better, tutor.worse, tutor.same) == (1, 1, 1)


def test_the_report_is_deterministic_and_has_the_numbers(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    first = render_report(RECORDS, path)
    assert first == render_report(RECORDS, path)
    assert "| `tutor-1` | 3 | 6 | 0.67 [" in first
    assert "| 1 | 2 | 1 | 1 | 3 |" in first  # level 1: 2 hints, 1 own, 1 fallback, median words
    assert "`p/a`: 0.00 → 1.00 (+1.00)" in first  # helped most


def test_bootstrap_mean_ci_basics() -> None:
    assert bootstrap_mean_ci([]) is None
    assert bootstrap_mean_ci([0.5, 0.5, 0.5]) == (0.5, 0.5)
    low, high = bootstrap_mean_ci([0.0, 1.0] * 10)
    assert low < 0.5 < high
