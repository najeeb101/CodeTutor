"""End-to-end grader tests: real child processes, adversarial submissions (brief section 2.5)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import pytest

from codetutor.grader import (
    GRADER_VERSION,
    GraderError,
    GradeResult,
    GradeStatus,
    Limits,
    TestStatus,
    grade,
    grade_many,
)
from codetutor.problems import Problem
from conftest import valid_problem_data

SUBMISSIONS = Path(__file__).parent / "submissions"

# Small limits keep the suite fast. Total is automatic: 8 tests * 0.5 s + 3 s = 7 s.
FAST = Limits(per_test_timeout_s=0.5, memory_mb=256)
# For submissions that hang at the top level, a short explicit total limit.
SHORT_TOTAL = Limits(per_test_timeout_s=0.5, total_timeout_s=2.0, memory_mb=256)


def submission(name: str) -> str:
    return (SUBMISSIONS / f"{name}.py").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sum_problem() -> Problem:
    """sum_of_evens: visible inputs 10, 7, 2, 1; hidden inputs 0, -5, 100, 11."""
    return Problem.model_validate(valid_problem_data())


@pytest.fixture(scope="module")
def evens_problem() -> Problem:
    """evens(nums) -> list of the even numbers, in order. List in, list out."""
    cases: list[tuple[list[int], list[int]]] = [
        ([1, 2, 3, 4], [2, 4]),
        ([2], [2]),
        ([1, 3], []),
        ([6, 5, 4], [6, 4]),
        ([], []),
        ([0], [0]),
        ([-2, -1], [-2]),
        ([8, 8, 1], [8, 8]),
    ]
    tests = [
        {"id": f"t{i:02}", "input": [nums], "expected": want, "hidden": i > 4, "compare": "exact"}
        for i, (nums, want) in enumerate(cases, start=1)
    ]
    data: dict[str, Any] = {
        **valid_problem_data(),
        "id": "cs1.lists.evens",
        "function_name": "evens",
        "tests": tests,
        "starter_code": "def evens(nums):\n    pass\n",
        "solution_code": "def evens(nums):\n    return [x for x in nums if x % 2 == 0]\n",
        "buggy": {},
    }
    return Problem.model_validate(data)


def statuses(result: GradeResult) -> dict[str, TestStatus]:
    return {test.test_id: test.status for test in result.tests}


# --- The adversarial table (brief section 2.5) ---


def test_correct_solution(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("correct"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED
    assert result.reward == 1.0
    assert result.passed == result.total == 8


def test_off_by_one_gets_partial_credit(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("off_by_one"), limits=FAST)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert 0 < result.reward < 1


def test_returns_none(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("returns_none"), limits=FAST)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert result.reward == 0.0


def test_index_error_on_some_tests(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("index_error_some"), limits=FAST, reveal_hidden=True)
    # Odd inputs (7, 1, -5, 11) raise; the even ones are still graded and pass.
    assert result.status == GradeStatus.RUNTIME_ERROR  # first failing test (t02) is an error
    assert statuses(result)["t02"] == TestStatus.RUNTIME_ERROR
    assert statuses(result)["t01"] == TestStatus.PASSED
    assert result.passed == 4
    assert "IndexError" in result.tests[1].error


def test_syntax_error_reports_line(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("syntax_error"), limits=FAST)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.reward == 0.0
    assert result.tests == []
    assert "SyntaxError" in result.compile_error
    assert "line 2" in result.compile_error


def test_misspelled_function(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("misspelled"), limits=FAST)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.compile_error == "Function 'sum_of_evens' was not defined."


def test_top_level_code_raises(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("toplevel_raises"), limits=FAST)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.compile_error == "RuntimeError: boom at import time"


def test_infinite_loop_in_function_times_out_only_that_test(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("infinite_loop_some"), limits=FAST)
    assert statuses(result)["t06"] == TestStatus.TIMEOUT  # input -5
    assert result.passed == 7  # the other tests still ran
    assert result.status == GradeStatus.TIMEOUT
    assert result.reward == 0.875


def test_infinite_loop_at_top_level(sum_problem: Problem) -> None:
    start = time.perf_counter()
    result = grade(sum_problem, submission("infinite_loop_toplevel"), limits=SHORT_TOTAL)
    assert result.status == GradeStatus.TIMEOUT
    assert result.reward == 0.0
    assert "Total time limit" in result.error
    assert time.perf_counter() - start < 5  # the grader doesn't hang


def test_deep_recursion(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("deep_recursion"), limits=FAST, reveal_hidden=True)
    assert result.status == GradeStatus.RUNTIME_ERROR
    assert "RecursionError" in result.tests[0].error


@pytest.mark.parametrize("name", ["memory_bomb", "memory_bomb_growing"])
def test_memory_bomb(sum_problem: Problem, name: str) -> None:
    result = grade(sum_problem, submission(name), limits=FAST, reveal_hidden=True)
    assert result.status in {GradeStatus.RUNTIME_ERROR, GradeStatus.CRASHED}
    if result.status == GradeStatus.RUNTIME_ERROR:
        assert "MemoryError" in result.tests[0].error


def test_print_flood_is_truncated(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("print_flood"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED
    assert len(result.stdout) <= FAST.max_output_bytes + 100
    assert result.stdout.endswith("[output truncated]")


def test_fake_token_is_ignored(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("fake_token"), limits=FAST)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert result.reward == 0.0


def test_writing_to_real_stdout_is_ignored(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("write_real_stdout"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED


def test_sys_exit_in_function(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("sys_exit"), limits=FAST, reveal_hidden=True)
    assert result.status == GradeStatus.RUNTIME_ERROR
    assert "SystemExit" in result.tests[0].error


def test_os_exit_in_function(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("os_exit"), limits=FAST)
    assert result.status == GradeStatus.CRASHED
    assert result.reward == 0.0


def test_mutating_input_does_not_affect_other_tests(evens_problem: Problem) -> None:
    result = grade(evens_problem, submission("evens_correct"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED


def test_returning_bool_instead_of_int(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("returns_bool"), limits=FAST)
    # n = 1, 0 and -5 expect 0 but get False.
    assert statuses(result)["t04"] == TestStatus.WRONG_ANSWER
    assert result.passed == 5


def test_returning_tuple_instead_of_list(evens_problem: Problem) -> None:
    result = grade(evens_problem, submission("returns_tuple"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED


def test_returning_set_explains_why(evens_problem: Problem) -> None:
    result = grade(evens_problem, submission("returns_set"), limits=FAST)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert "return a list instead" in result.tests[0].error


# --- Optional check: the function must not change its input (check_input_unchanged) ---
# Off by default: test_mutating_input_does_not_affect_other_tests shows the same code accepted.


def test_changing_the_input_fails_when_the_problem_checks_it(evens_problem: Problem) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(checked, submission("evens_correct"), limits=FAST)  # right answers, clears nums
    assert result.status == GradeStatus.WRONG_ANSWER
    assert "changed its input" in result.tests[0].error
    assert statuses(result)["t05"] == TestStatus.PASSED  # input []: clear() changes nothing
    # The message says nothing about the input, so hidden tests may show it too.
    hidden = result.tests[5]
    assert not hidden.revealed
    assert "changed its input" in hidden.error


def test_input_check_gives_no_false_alarm(evens_problem: Problem) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(checked, checked.solution_code, limits=FAST)
    assert result.status == GradeStatus.ACCEPTED


def test_input_check_survives_objects_whose_equality_raises(evens_problem: Problem) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(checked, submission("input_eq_raises"), limits=FAST)
    assert result.status == GradeStatus.WRONG_ANSWER  # not crashed
    assert "changed its input" in result.tests[0].error


def test_big_file_is_stopped(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("big_file"), limits=FAST, reveal_hidden=True)
    assert result.status in {GradeStatus.RUNTIME_ERROR, GradeStatus.CRASHED}
    if result.status == GradeStatus.RUNTIME_ERROR:
        assert "File too large" in result.tests[0].error


def test_sleep_at_top_level(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("sleep_toplevel"), limits=SHORT_TOTAL)
    assert result.status == GradeStatus.TIMEOUT


def _process_is_gone(pid: int) -> bool:
    """True if the process no longer exists (or is a zombie waiting to be cleaned up)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    status = Path(f"/proc/{pid}/status")
    return status.exists() and "State:\tZ" in status.read_text()


def test_spawned_process_is_killed(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("spawn_forever"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED
    match = re.search(r"CHILD_PID=(\d+)", result.stdout)
    assert match, result.stdout
    pid = int(match.group(1))
    deadline = time.monotonic() + 2
    while not _process_is_gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _process_is_gone(pid), f"process {pid} is still running"


def test_thread_left_running_does_not_cause_timeout(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("thread_forever"), limits=FAST)
    assert result.status == GradeStatus.ACCEPTED
    assert result.duration_ms < 3000


# --- Hidden tests don't leak ---


def test_hidden_details_are_hidden_by_default(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("prints_hidden_input"), limits=FAST)
    hidden = [test for test in result.tests if test.hidden]
    assert hidden and all(not test.revealed for test in hidden)
    assert all(test.input is None and test.actual is None for test in hidden)
    # print() output and error messages from hidden tests are not shown (they could contain inputs)
    assert "SECRET_INPUT=10" in result.stdout  # visible test: shown
    assert "SECRET_INPUT=100" not in result.stdout  # hidden test: not shown
    failing = next(test for test in result.tests if test.status == TestStatus.RUNTIME_ERROR)
    assert failing.error == "ValueError"


def test_reveal_hidden_shows_everything(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("prints_hidden_input"), limits=FAST, reveal_hidden=True)
    assert all(test.revealed for test in result.tests)
    assert "SECRET_INPUT=100" in result.stdout
    failing = next(test for test in result.tests if test.status == TestStatus.RUNTIME_ERROR)
    assert failing.error == "ValueError: the input was 100"


# --- API properties ---


def test_result_is_json_serializable(sum_problem: Problem) -> None:
    result = grade(sum_problem, submission("off_by_one"), limits=FAST, reveal_hidden=True)
    text = result.model_dump_json()
    assert json.loads(text)["grader_version"] == GRADER_VERSION
    assert GradeResult.model_validate_json(text) == result


def test_grading_is_deterministic(sum_problem: Problem) -> None:
    def without_durations(result: GradeResult) -> dict[str, Any]:
        data = result.model_dump(exclude={"duration_ms"})
        for test in data["tests"]:
            del test["duration_ms"]
        return data

    code = submission("index_error_some")
    first = grade(sum_problem, code, limits=FAST, reveal_hidden=True)
    second = grade(sum_problem, code, limits=FAST, reveal_hidden=True)
    assert without_durations(first) == without_durations(second)


def test_grade_many_keeps_order(sum_problem: Problem, evens_problem: Problem) -> None:
    jobs = [
        (sum_problem, submission("correct")),
        (sum_problem, submission("syntax_error")),
        (evens_problem, submission("evens_correct")),
        (sum_problem, submission("off_by_one")),
        (sum_problem, submission("returns_none")),
    ]
    results = grade_many(jobs, workers=3, limits=FAST)
    assert [r.status for r in results] == [
        GradeStatus.ACCEPTED,
        GradeStatus.COMPILE_ERROR,
        GradeStatus.ACCEPTED,
        GradeStatus.WRONG_ANSWER,
        GradeStatus.WRONG_ANSWER,
    ]
    assert [r.problem_id for r in results][2] == "cs1.lists.evens"
    assert all(r.tests[0].revealed for r in results if r.tests)  # evals see everything


def test_problem_time_limit_is_used_when_no_limits_given(sum_problem: Problem) -> None:
    slow = sum_problem.model_copy(update={"time_limit_s": 0.3})
    result = grade(slow, submission("infinite_loop_some"))
    timed_out = next(t for t in result.tests if t.status == TestStatus.TIMEOUT)
    assert timed_out.duration_ms < 1000


def test_missing_expected_values_is_a_clear_error(sum_problem: Problem) -> None:
    data = valid_problem_data()
    del data["tests"][0]["expected"]
    problem = Problem.model_validate(data)
    with pytest.raises(GraderError, match="t01"):
        grade(problem, submission("correct"))
