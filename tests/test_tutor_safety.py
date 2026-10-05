"""The tutor safety run (Week 4 Step 2): situations, records, the report, and the CLI's errors."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from codetutor.grader import SubprocessSandbox
from codetutor.problems import Problem
from codetutor.tutor.safety import (
    INJECTION_COMMENT,
    INJECTION_QUESTION,
    build_situations,
    copies_a_reference_hint,
    read_records,
    render_report,
    results_path,
    run_safety,
    write_records,
)
from codetutor.tutor.service import TutorConfig
from conftest import REPO_ROOT, ScriptedModel, valid_problem_data

COMMENTED_BUGGY = """def sum_of_evens(n: int) -> int:
    # bug: range stops before n
    return sum(range(2, n, 2))  # off by one
"""


@pytest.fixture(scope="module")
def problem() -> Problem:
    data = valid_problem_data()
    data["buggy"] = {"off_by_one": COMMENTED_BUGGY}
    return Problem.model_validate(data)


@pytest.fixture(scope="module")
def situations(problem: Problem) -> list:
    return build_situations([problem], sandbox=SubprocessSandbox())


def test_situations_hide_the_bug_comments_and_the_hidden_tests(situations: list) -> None:
    normal, injected = situations
    assert normal.code == "def sum_of_evens(n: int) -> int:\n    return sum(range(2, n, 2))\n"
    assert normal.result.status == "wrong_answer"
    assert not any(test.revealed for test in normal.result.tests if test.hidden)
    assert (injected.injected, injected.question) == (True, INJECTION_QUESTION)
    assert injected.code == INJECTION_COMMENT + normal.code


def test_the_run_asks_level_1_then_level_2_with_the_earlier_hint(situations: list) -> None:
    first = "Which numbers does your range really produce?"
    model = ScriptedModel(first, "Look at the stop value of range: is n itself included?", first)
    records = run_safety(situations, model, session=None, embedder=None, config=TutorConfig())
    assert [(r["level"], r["injected"]) for r in records] == [(1, False), (2, False), (1, True)]
    assert f"- {first}" in model.calls[1][-1]["content"]  # level 2 knows the level 1 hint
    assert records[0]["visible_failed"] == 2 and records[0]["source"] == "model"
    assert records[2]["text"] == first and records[2]["copies_reference"] is False


def test_copies_of_a_teachers_hint_are_counted() -> None:
    data = valid_problem_data()
    data["hints"][0] = "Check the stop value of range: the last number is never included."
    problem = Problem.model_validate(data)
    assert copies_a_reference_hint(
        "Check the stop value of range: the last number is never!", problem
    )
    assert not copies_a_reference_hint("Which even numbers should be added for n = 10?", problem)
    assert not copies_a_reference_hint("Hi", problem)


def _record(**changes: Any) -> dict[str, Any]:
    attempt = {"issues": [], "error": None, "prompt_tokens": 1000, "prompt_chars": 4000}
    record = {
        "injected": False,
        "level": 1,
        "source": "model",
        "text": "one two three four",
        "copies_reference": False,
        "latency_ms": 2000.0,
        "attempts": [attempt],
    }
    record.update(changes)
    return record


def test_the_report_counts_blocks_retries_and_references() -> None:
    blocked = {
        "issues": [{"kind": "code_block", "detail": "x"}],
        "error": None,
        "prompt_tokens": 1500,
        "prompt_chars": 5000,
    }
    too_long = {"issues": [], "error": "prompt too long: about 2100 tokens", "prompt_tokens": None}
    records = [
        _record(),
        _record(attempts=[blocked, _record()["attempts"][0]]),  # fixed by the retry
        _record(source="fallback", attempts=[blocked, blocked], text="Hint one."),
        _record(level=2, copies_reference=True),
        _record(injected=True, latency_ms=4000.0, attempts=[too_long]),
    ]
    report = render_report({"fake/m": records})
    level_1 = (
        "| `fake/m` | level 1 | 3 | 2 (67%) | 1 of 2 | 1 (33%) | 0 | 0 (0%) | 4 / 4 | 2.0 / 2.0 |"
    )
    assert f"{level_1} 1500 |" in report
    assert "| `fake/m` | level 2 | 1 | 0 (0%) | 0 of 0 | 0 (0%) | 0 | 1 (100%) |" in report
    assert "| `fake/m` | 0 | 2 | 0 | 0 | 0 |" in report  # first attempts: 2 code_block
    assert "- `fake/m`: prompt too long: 1" in report
    assert "- `fake/m`: 3.33" in report
    assert report == render_report({"fake/m": records})


def test_records_round_trip_and_file_names(tmp_path: Path) -> None:
    path = results_path(tmp_path, "ollama/qwen2.5-coder:7b")
    assert path.name == "safety-ollama-qwen2.5-coder-7b.jsonl"
    write_records(path, [_record(), _record(level=2)])
    assert read_records(path) == [_record(), _record(level=2)]


def test_ask_tutor_refuses_an_unknown_problem(tmp_path: Path) -> None:
    code = tmp_path / "x.py"
    code.write_text("x = 1\n")
    script = str(REPO_ROOT / "scripts" / "ask_tutor.py")
    done = subprocess.run(
        [sys.executable, script, "cs1.nope.missing", str(code), "--no-save"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert done.returncode == 1 and "unknown problem 'cs1.nope.missing'" in done.stderr
    wrong_level = subprocess.run(
        [sys.executable, script, "cs1.loops.fizzbuzz", str(code), "--level", "4"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert wrong_level.returncode == 2 and "invalid choice: 4" in wrong_level.stderr
