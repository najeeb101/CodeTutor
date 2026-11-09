"""End-to-end grader tests: real child processes, adversarial submissions (brief section 2.5)."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from codetutor.grader import (
    GRADER_VERSION,
    DockerSandbox,
    GraderError,
    GradeResult,
    GradeStatus,
    Limits,
    Sandbox,
    SubprocessSandbox,
    TestStatus,
    grade,
    grade_many,
)
from codetutor.grader.models import RawResult
from codetutor.grader.sandbox import (
    DOCKER_LABEL,
    DOCKER_PIDS_LIMIT,
    DOCKER_START_MARGIN_S,
    _cpu_limit_as_timeout,
    _signal_returncode,
)
from codetutor.problems import Problem
from conftest import docker_runtime, valid_problem_data

SUBMISSIONS = Path(__file__).parent / "submissions"

# Small limits keep the suite fast. Total is automatic: 8 tests * 0.5 s + 3 s = 7 s.
FAST = Limits(per_test_timeout_s=0.5, memory_mb=256)
# For submissions that hang at the top level, a short explicit total limit.
SHORT_TOTAL = Limits(per_test_timeout_s=0.5, total_timeout_s=2.0, memory_mb=256)
# Memory bombs must be stopped by the memory limit, not the timer. Filling 256 MB usually takes
# ~150 ms, but under load it was measured at up to ~500 ms on WSL2, so a 0.5 s timer sometimes
# won the race and the test failed (Q12). 2 s still lost the race 4 times in ~60 full runs on
# 2026-10-01..07 (Q14, always a `timeout` in the growing bomb, also on mains power), so it is 3 s.
# The assertion is unchanged: a broken memory limit would still fail the test.
MEMORY_TEST = Limits(per_test_timeout_s=3.0, memory_mb=256)


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


# --- Sandbox backends: the adversarial tests run on both ---
# The docker ones are opt-in (`make test-docker`): each container start costs ~0.7 s.
BACKENDS = ["subprocess", pytest.param("docker", marks=pytest.mark.docker)]


def _leftover_containers() -> list[str]:
    """Names of our sandbox containers that still exist (running or stopped)."""
    ps = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"label={DOCKER_LABEL}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    return ps.stdout.split()


@pytest.fixture(scope="module")
def docker_sandbox() -> DockerSandbox:
    # Fails loudly without Docker: you asked for the docker tests. CI runs them a second time
    # under gVisor (TEST_SANDBOX_RUNTIME=runsc, Deploy Step 3): the same statuses must come out.
    return DockerSandbox(runtime=docker_runtime())


@pytest.fixture(params=BACKENDS)
def sandbox(request: pytest.FixtureRequest) -> Iterator[Sandbox]:
    if request.param == "subprocess":
        yield SubprocessSandbox()
        return
    yield request.getfixturevalue("docker_sandbox")
    # Nothing may be left behind: a container that is still running keeps the student's code
    # alive. (--rm removes stopped containers in the background, so allow a moment.)
    deadline = time.monotonic() + 5
    while _leftover_containers() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _leftover_containers() == [], "a sandbox container was left behind"


def start_margin_s(sandbox: Sandbox) -> float:
    """Extra time a backend needs before student code starts (Docker: starting the container)."""
    return DOCKER_START_MARGIN_S if isinstance(sandbox, DockerSandbox) else 0.0


# --- The adversarial table (brief section 2.5) ---


def test_correct_solution(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("correct"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    assert result.reward == 1.0
    assert result.passed == result.total == 8


def test_off_by_one_gets_partial_credit(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("off_by_one"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert 0 < result.reward < 1


def test_returns_none(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("returns_none"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert result.reward == 0.0


def test_index_error_on_some_tests(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(
        sum_problem,
        submission("index_error_some"),
        limits=FAST,
        sandbox=sandbox,
        reveal_hidden=True,
    )
    # Odd inputs (7, 1, -5, 11) raise; the even ones are still graded and pass.
    assert result.status == GradeStatus.RUNTIME_ERROR  # first failing test (t02) is an error
    assert statuses(result)["t02"] == TestStatus.RUNTIME_ERROR
    assert statuses(result)["t01"] == TestStatus.PASSED
    assert result.passed == 4
    assert "IndexError" in result.tests[1].error


def test_syntax_error_reports_line(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("syntax_error"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.reward == 0.0
    assert result.tests == []
    assert "SyntaxError" in result.compile_error
    assert "line 2" in result.compile_error


def test_misspelled_function(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("misspelled"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.compile_error == "Function 'sum_of_evens' was not defined."


def test_top_level_code_raises(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("toplevel_raises"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.COMPILE_ERROR
    assert result.compile_error == "RuntimeError: boom at import time"


def test_infinite_loop_in_function_times_out_only_that_test(
    sum_problem: Problem, sandbox: Sandbox
) -> None:
    result = grade(sum_problem, submission("infinite_loop_some"), limits=FAST, sandbox=sandbox)
    assert statuses(result)["t06"] == TestStatus.TIMEOUT  # input -5
    assert result.passed == 7  # the other tests still ran
    assert result.status == GradeStatus.TIMEOUT
    assert result.reward == 0.875


def test_infinite_loop_at_top_level(sum_problem: Problem, sandbox: Sandbox) -> None:
    start = time.perf_counter()
    result = grade(
        sum_problem, submission("infinite_loop_toplevel"), limits=SHORT_TOTAL, sandbox=sandbox
    )
    assert result.status == GradeStatus.TIMEOUT
    assert result.reward == 0.0
    assert "Total time limit" in result.error
    assert time.perf_counter() - start < 5 + start_margin_s(sandbox)  # the grader doesn't hang


def test_cpu_limit_counts_as_timeout(sum_problem: Problem) -> None:
    # Threads in C code (hashlib) use CPU time faster than wall time, so the runner's CPU limit
    # usually fires first (measured: 4/4 at ~2.4 s, wall limit 7 s). Either way it is a time
    # limit: timeout, not crashed (Q13). Subprocess only: in Docker, --cpus 1 stops threads from
    # beating wall time; Docker's CPU-limit path is test_infinite_loop_at_top_level[docker].
    result = grade(sum_problem, submission("cpu_threads"), limits=FAST)
    assert result.status == GradeStatus.TIMEOUT
    assert result.reward == 0.0


def _raw(returncode: int | None, timed_out: bool = False) -> RawResult:
    return RawResult(
        returncode=returncode,
        stdout="",
        stderr="",
        timed_out=timed_out,
        output_overflow=False,
        duration_ms=1.0,
    )


def test_cpu_limit_kill_is_reported_as_timeout() -> None:
    assert _cpu_limit_as_timeout(_raw(-signal.SIGXCPU)).timed_out
    assert not _cpu_limit_as_timeout(_raw(-signal.SIGKILL)).timed_out  # e.g. docker kill, OOM
    assert not _cpu_limit_as_timeout(_raw(0)).timed_out


@pytest.mark.parametrize(
    ("docker_code", "expected"),
    [
        (137, -signal.SIGKILL),  # 128 + 9
        (152, -signal.SIGXCPU),  # 128 + 24
        (160, 160),  # 128 + 32: not a real signal, stays unchanged
        (1, 1),
        (0, 0),
        (None, None),
    ],
)
def test_docker_exit_codes_become_signals(docker_code: int | None, expected: int | None) -> None:
    assert _signal_returncode(docker_code) == expected


def test_deep_recursion(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(
        sum_problem, submission("deep_recursion"), limits=FAST, sandbox=sandbox, reveal_hidden=True
    )
    assert result.status == GradeStatus.RUNTIME_ERROR
    assert "RecursionError" in result.tests[0].error


@pytest.mark.parametrize("name", ["memory_bomb", "memory_bomb_growing"])
def test_memory_bomb(sum_problem: Problem, name: str, sandbox: Sandbox) -> None:
    result = grade(
        sum_problem, submission(name), limits=MEMORY_TEST, sandbox=sandbox, reveal_hidden=True
    )
    # If the memory limit stopped working, the bomb would hit the 2 s timer (timeout) and fail.
    assert result.status in {GradeStatus.RUNTIME_ERROR, GradeStatus.CRASHED}
    if result.status == GradeStatus.RUNTIME_ERROR:
        assert "MemoryError" in result.tests[0].error


def test_print_flood_is_truncated(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("print_flood"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    assert len(result.stdout) <= FAST.max_output_bytes + 100
    assert result.stdout.endswith("[output truncated]")


def test_fake_token_is_ignored(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("fake_token"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert result.reward == 0.0


def test_writing_to_real_stdout_is_ignored(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("write_real_stdout"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED


def test_sys_exit_in_function(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(
        sum_problem, submission("sys_exit"), limits=FAST, sandbox=sandbox, reveal_hidden=True
    )
    assert result.status == GradeStatus.RUNTIME_ERROR
    assert "SystemExit" in result.tests[0].error


def test_os_exit_in_function(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("os_exit"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.CRASHED
    assert result.reward == 0.0


def test_mutating_input_does_not_affect_other_tests(
    evens_problem: Problem, sandbox: Sandbox
) -> None:
    result = grade(evens_problem, submission("evens_correct"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED


def test_returning_bool_instead_of_int(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("returns_bool"), limits=FAST, sandbox=sandbox)
    # n = 1, 0 and -5 expect 0 but get False.
    assert statuses(result)["t04"] == TestStatus.WRONG_ANSWER
    assert result.passed == 5


def test_returning_tuple_instead_of_list(evens_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(evens_problem, submission("returns_tuple"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED


def test_returning_set_explains_why(evens_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(evens_problem, submission("returns_set"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.WRONG_ANSWER
    assert "return a list instead" in result.tests[0].error


# --- Optional check: the function must not change its input (check_input_unchanged) ---
# Off by default: test_mutating_input_does_not_affect_other_tests shows the same code accepted.


def test_changing_the_input_fails_when_the_problem_checks_it(
    evens_problem: Problem, sandbox: Sandbox
) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(
        checked, submission("evens_correct"), limits=FAST, sandbox=sandbox
    )  # right answers, clears nums
    assert result.status == GradeStatus.WRONG_ANSWER
    assert "changed its input" in result.tests[0].error
    assert statuses(result)["t05"] == TestStatus.PASSED  # input []: clear() changes nothing
    # The message says nothing about the input, so hidden tests may show it too.
    hidden = result.tests[5]
    assert not hidden.revealed
    assert "changed its input" in hidden.error


def test_input_check_gives_no_false_alarm(evens_problem: Problem, sandbox: Sandbox) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(checked, checked.solution_code, limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED


def test_input_check_survives_objects_whose_equality_raises(
    evens_problem: Problem, sandbox: Sandbox
) -> None:
    checked = evens_problem.model_copy(update={"check_input_unchanged": True})
    result = grade(checked, submission("input_eq_raises"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.WRONG_ANSWER  # not crashed
    assert "changed its input" in result.tests[0].error


def test_big_file_is_stopped(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(
        sum_problem, submission("big_file"), limits=FAST, sandbox=sandbox, reveal_hidden=True
    )
    assert result.status in {GradeStatus.RUNTIME_ERROR, GradeStatus.CRASHED}
    if result.status == GradeStatus.RUNTIME_ERROR:
        assert "File too large" in result.tests[0].error


def test_sleep_at_top_level(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("sleep_toplevel"), limits=SHORT_TOTAL, sandbox=sandbox)
    assert result.status == GradeStatus.TIMEOUT


def _process_is_gone(pid: int) -> bool:
    """True if the process no longer exists (or is a zombie waiting to be cleaned up)."""
    try:
        os.kill(pid, 0)
        return "State:\tZ" in Path(f"/proc/{pid}/status").read_text()
    except (ProcessLookupError, FileNotFoundError):
        # Gone, possibly between the two checks: a zombie can be cleaned up at any moment, and
        # reading its /proc file then raises ProcessLookupError (seen once in a full run).
        return True


def test_spawned_process_is_killed(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("spawn_forever"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    match = re.search(r"CHILD_PID=(\d+)", result.stdout)
    assert match, result.stdout
    if isinstance(sandbox, DockerSandbox):
        return  # that PID exists only inside the container; the fixture checks it is gone
    pid = int(match.group(1))
    deadline = time.monotonic() + 2
    while not _process_is_gone(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _process_is_gone(pid), f"process {pid} is still running"


def test_thread_left_running_does_not_cause_timeout(sum_problem: Problem, sandbox: Sandbox) -> None:
    result = grade(sum_problem, submission("thread_forever"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    assert result.duration_ms < 3000 + 1000 * start_margin_s(sandbox)


# --- Threat model: what only Docker blocks (docs/grader.md, section 5) ---


def test_host_files_are_not_readable(
    sum_problem: Problem, sandbox: Sandbox, tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if isinstance(sandbox, SubprocessSandbox):
        # Strict: if this ever passes, the limitation is gone and the docs must change.
        reason = "known limitation: the subprocess sandbox can read your files"
        request.applymarker(pytest.mark.xfail(strict=True, reason=reason))
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")
    code = submission("reads_host_file").replace("__SECRET_PATH__", str(secret))
    result = grade(sum_problem, code, limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    assert "STOLEN" not in result.stdout
    assert "BLOCKED=FileNotFoundError" in result.stdout


def test_network_is_blocked(sum_problem: Problem, sandbox: Sandbox) -> None:
    if isinstance(sandbox, SubprocessSandbox):
        pytest.skip("known limitation; the test would really connect to the internet")
    result = grade(sum_problem, submission("network_access"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    assert "CONNECTED" not in result.stdout
    assert "BLOCKED=" in result.stdout


def test_process_limit_stops_fork_bombs(sum_problem: Problem, sandbox: Sandbox) -> None:
    if isinstance(sandbox, SubprocessSandbox):
        pytest.skip("no process limit in the subprocess sandbox (decision Q6)")
    result = grade(sum_problem, submission("many_processes"), limits=FAST, sandbox=sandbox)
    assert result.status == GradeStatus.ACCEPTED
    match = re.search(r"STARTED=(\d+)", result.stdout)
    assert match, result.stdout
    assert 0 < int(match.group(1)) < DOCKER_PIDS_LIMIT


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


def test_grading_is_deterministic(sum_problem: Problem, sandbox: Sandbox) -> None:
    def without_durations(result: GradeResult) -> dict[str, Any]:
        data = result.model_dump(exclude={"duration_ms"})
        for test in data["tests"]:
            del test["duration_ms"]
        return data

    code = submission("index_error_some")
    first = grade(sum_problem, code, limits=FAST, reveal_hidden=True, sandbox=sandbox)
    second = grade(sum_problem, code, limits=FAST, reveal_hidden=True, sandbox=sandbox)
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
