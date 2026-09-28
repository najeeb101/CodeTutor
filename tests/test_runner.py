"""Tests for runner.py on its own: run it as a real child process and read its report."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any

from codetutor.grader.sandbox import CHILD_ENV, PYTHON_FLAGS, RUNNER_PATH

TOKEN = "TESTTOKEN1234"


def run_runner(code: str, inputs: list[list[Any]], **overrides: Any) -> dict[str, Any]:
    """Run runner.py directly with a hand-made job and return the parsed report."""
    job = {
        "token": TOKEN,
        "code": code,
        "function_name": "f",
        "tests": [{"id": f"t{i}", "input": args} for i, args in enumerate(inputs)],
        "per_test_timeout_s": 1.0,
        "total_timeout_s": 10.0,
        "memory_mb": 256,
        "max_file_mb": 1,
        "max_output_bytes": 1000,
        "max_return_bytes": 1_000_000,
        **overrides,
    }
    completed = subprocess.run(
        [sys.executable, *PYTHON_FLAGS, str(RUNNER_PATH)],
        input=json.dumps(job).encode(),
        capture_output=True,
        env=CHILD_ENV,
        timeout=15,
    )
    stdout = completed.stdout.decode()
    assert TOKEN in stdout, completed.stderr.decode()
    return json.loads(stdout[stdout.rfind(TOKEN) + len(TOKEN) :])


def test_report_has_actual_values_but_no_pass_fail() -> None:
    report = run_runner("def f(x):\n    return x * 2\n", [[1], [5]])
    assert report["load"] == {"ok": True, "error": None, "stdout": ""}
    assert [t["actual"] for t in report["tests"]] == [2, 10]
    assert all(t["outcome"] == "returned" for t in report["tests"])
    assert "passed" not in json.dumps(report)  # the runner never decides pass/fail


def test_tuple_is_returned_as_list() -> None:
    report = run_runner("def f():\n    return (1, (2, 3))\n", [[]])
    assert report["tests"][0]["actual"] == [1, [2, 3]]


def test_bad_return_values_get_a_message_not_a_repr() -> None:
    code = """
class Thing:
    pass

def f(kind):
    loop = []
    loop.append(loop)
    return {
        "set": {1, 2},
        "nan": float("nan"),
        "object": Thing(),
        "int_keys": {1: "a"},
        "self_reference": loop,
    }[kind]
"""
    kinds = ["set", "nan", "object", "int_keys", "self_reference"]
    report = run_runner(code, [[kind] for kind in kinds])
    errors = {kind: t["error"] for kind, t in zip(kinds, report["tests"], strict=True)}
    assert all(t["outcome"] == "bad_return" for t in report["tests"])
    assert "return a list instead" in errors["set"]
    assert "NaN" in errors["nan"]
    assert "Thing" in errors["object"]
    assert "non-string keys" in errors["int_keys"]
    assert "nested too deeply" in errors["self_reference"]


def test_too_large_return_value() -> None:
    report = run_runner("def f():\n    return 'x' * 2000\n", [[]], max_return_bytes=1000)
    assert report["tests"][0]["outcome"] == "bad_return"
    assert "too large" in report["tests"][0]["error"]


def test_output_is_captured_per_test_and_capped() -> None:
    code = "print('loading')\ndef f(x):\n    print('x' * x)\n    return x\n"
    report = run_runner(code, [[3], [5000], [2]], max_output_bytes=100)
    assert report["load"]["stdout"] == "loading\n"
    assert report["tests"][0]["stdout"] == "xxx\n"
    assert len(report["tests"][1]["stdout"]) < 100
    assert report["tests"][2]["stdout"] == ""  # budget already used up
    assert report["stdout_truncated"] is True


def test_each_test_gets_a_fresh_copy_of_its_input() -> None:
    code = (
        "saved = []\n"
        "def f(nums):\n"
        "    saved.append(nums)\n"
        "    nums.append(99)\n"
        "    return len(saved[0])\n"
    )
    report = run_runner(code, [[[1, 2]], [[1, 2]]])
    # The first input was mutated once (length 3) but later tests got their own copies.
    assert [t["actual"] for t in report["tests"]] == [3, 3]


def test_timeout_is_per_test() -> None:
    code = "def f(x):\n    while x:\n        pass\n    return 0\n"
    report = run_runner(code, [[0], [1], [0]], per_test_timeout_s=0.3)
    assert [t["outcome"] for t in report["tests"]] == ["returned", "timeout", "returned"]


def test_student_catching_exception_cannot_swallow_timeout() -> None:
    code = (
        "def f():\n"
        "    while True:\n"
        "        try:\n"
        "            pass\n"
        "        except Exception:\n"
        "            pass\n"
    )
    report = run_runner(code, [[]], per_test_timeout_s=0.3)
    assert report["tests"][0]["outcome"] == "timeout"


def test_runner_exits_even_if_student_starts_a_thread() -> None:
    code = (
        "import threading, time\n"
        "threading.Thread(target=time.sleep, args=(60,)).start()\n"
        "def f():\n"
        "    return 1\n"
    )
    start = time.perf_counter()
    report = run_runner(code, [[]])
    assert report["tests"][0]["actual"] == 1
    assert time.perf_counter() - start < 5


def test_missing_function_message() -> None:
    report = run_runner("def g():\n    pass\n", [[]])
    assert report["load"] == {"ok": False, "error": "Function 'f' was not defined.", "stdout": ""}
    assert report["tests"] == []


def test_site_packages_are_not_importable() -> None:
    report = run_runner("import pydantic\ndef f():\n    return 1\n", [[]])
    assert report["load"]["ok"] is False
    assert "ModuleNotFoundError" in report["load"]["error"]


def test_hash_seed_is_fixed() -> None:
    code = "def f():\n    return list({'apple', 'banana', 'cherry', 'date'})\n"
    first = run_runner(code, [[]])["tests"][0]["actual"]
    second = run_runner(code, [[]])["tests"][0]["actual"]
    assert first == second
