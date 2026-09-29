"""Runs INSIDE the sandbox child process. Executes student code and reports what happened.

Protocol:
  stdin : one JSON job {token, code, function_name, tests: [{id, input}], limits...}
  stdout: whatever the student wrote directly, then "\\n" + token + one JSON report at the end.
The parent reads only the text after the LAST token.

Rules for this file:
- Standard library only. It must never import `codetutor` (it runs with site-packages disabled).
- It never receives expected outputs, so student code can't read the answers from memory.
- It does not decide pass/fail. It reports return values (and whether the input changed);
  the parent compares.
"""

import io
import json
import math
import os
import resource
import signal
import sys
import time
import traceback

MB = 1024 * 1024


class _TestTimeout(BaseException):
    """Raised by the SIGALRM handler when a test runs too long.

    It subclasses BaseException (not Exception) so a student's `except Exception:` can't swallow it.
    A student's bare `except:` or `except BaseException:` still can; the parent's total time
    limit is the backstop for that.
    """


class _NotJson(Exception):
    """The student's return value can't be turned into JSON. The message explains why."""


class _CappedWriter(io.TextIOBase):
    """A text stream that keeps at most `limit` characters in total and drops the rest.

    One writer is shared by all sections (loading, test 1, test 2, ...). `take()` returns what was
    written since the last `take()`, so the output of each test can be reported separately.
    """

    def __init__(self, limit):
        self._limit = limit
        self._kept = 0
        self._parts = []
        self.truncated = False

    def writable(self):
        return True

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError(f"write() argument must be str, not {type(text).__name__}")
        room = self._limit - self._kept
        if len(text) > room:
            self.truncated = True
            text = text[: max(room, 0)]
        self._parts.append(text)
        self._kept += len(text)
        return len(text)

    def take(self):
        text = "".join(self._parts)
        self._parts = []
        return text


def _set_limits(job):
    """Apply resource limits to this process. Called BEFORE any student code runs.

    Soft and hard limits are equal, so student code can't raise them again.
    We don't set RLIMIT_NPROC: it counts all processes of the user, not just ours (decision Q6).
    """
    memory = job["memory_mb"] * MB
    cpu = math.ceil(job["total_timeout_s"]) + 1
    file_size = job["max_file_mb"] * MB
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _short_error(exc):
    """'IndexError: list index out of range', with the line number for syntax errors."""
    if isinstance(exc, SyntaxError):
        return f"{type(exc).__name__}: {exc.msg} (line {exc.lineno})"
    return traceback.format_exception_only(type(exc), exc)[-1].strip()


def _to_json_value(value):
    """Convert a return value into plain JSON data, or raise _NotJson with a helpful message.

    Tuples become lists. Sets and other objects are errors, not repr() strings: a repr string could
    accidentally equal an expected string answer.
    """
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _NotJson("returned NaN or infinity, which is not allowed")
        return float(value)
    if isinstance(value, list | tuple):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise _NotJson("returned a dict with non-string keys; use string keys")
        return {key: _to_json_value(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        raise _NotJson("returned a set; return a list instead")
    raise _NotJson(
        f"returned a {type(value).__name__} object; return a number, string, bool, None, "
        "list or dict"
    )


def _load(code, function_name):
    """Run the submission's top-level code. Return (function, None) or (None, error message)."""
    namespace = {"__name__": "__submission__"}
    try:
        compiled = compile(code, "<submission>", "exec")
        exec(compiled, namespace)
    except BaseException as exc:
        # BaseException, not Exception: top-level student code may call sys.exit() or raise
        # KeyboardInterrupt, and that must be reported as a compile error, not kill the runner.
        return None, _short_error(exc)
    function = namespace.get(function_name)
    if not callable(function):
        return None, f"Function '{function_name}' was not defined."
    return function, None


def _input_changed(args, original):
    """True if the function changed its arguments, e.g. sorted the input list in place.

    `args` is the copy the student's function received; `original` is the job's own copy, which
    student code is never given. Only a report: the parent decides if it matters (problem setting).
    """
    try:
        return bool(args != original)
    except BaseException:
        # BaseException on purpose: the student may have put their own objects into the list, and
        # their == can raise anything. A list we can't even compare has certainly changed.
        return True


def _run_test(function, test, timeout_s, max_return_bytes):
    """Call the function on one test input and describe what happened."""
    # A fresh copy of the input for every test, so mutating it can't affect anything else.
    args = json.loads(json.dumps(test["input"]))
    start = time.perf_counter()
    report = {"id": test["id"]}
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout_s)
        try:
            value = function(*args)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)  # always cancel the timer
    except _TestTimeout:
        report.update(outcome="timeout", error=f"Time limit exceeded ({timeout_s:g} s)")
    except RecursionError:
        report.update(outcome="error", error="RecursionError: maximum recursion depth exceeded")
    except BaseException as exc:
        # BaseException on purpose: student code may raise SystemExit (sys.exit) or
        # KeyboardInterrupt. Those must become a runtime error for this test, not stop the runner.
        report.update(outcome="error", error=_short_error(exc))
    else:
        report["input_changed"] = _input_changed(args, test["input"])
        try:
            actual = _to_json_value(value)
            if len(json.dumps(actual)) > max_return_bytes:
                raise _NotJson("return value is too large")
            report.update(outcome="returned", actual=actual)
        except _NotJson as exc:
            report.update(outcome="bad_return", error=str(exc))
        except RecursionError:
            report.update(outcome="bad_return", error="return value is nested too deeply")
    report["duration_ms"] = round((time.perf_counter() - start) * 1000, 3)
    return report


def _raise_timeout(signum, frame):
    raise _TestTimeout()


def _write_all(fd, data):
    """os.write may write only part of the data, so loop until everything is written."""
    while data:
        written = os.write(fd, data)
        data = data[written:]


def main():
    """Read the job, run the tests, write the report, and exit immediately."""
    job = json.loads(sys.stdin.buffer.read())
    _set_limits(job)
    signal.signal(signal.SIGALRM, _raise_timeout)

    # Capture everything the student prints. We also replace sys.__stdout__/__stderr__, which
    # student code could otherwise use to reach the real stdout. (It can still use os.write(1, ...);
    # that is harmless because the parent only trusts the text after the secret token.)
    output = _CappedWriter(job["max_output_bytes"])
    sys.stdout = sys.stderr = sys.__stdout__ = sys.__stderr__ = output

    function, error = _load(job["code"], job["function_name"])
    report = {"load": {"ok": function is not None, "error": error, "stdout": output.take()}}
    tests = []
    if function is not None:
        for test in job["tests"]:
            result = _run_test(function, test, job["per_test_timeout_s"], job["max_return_bytes"])
            result["stdout"] = output.take()
            tests.append(result)
    report["tests"] = tests
    report["stdout_truncated"] = output.truncated

    data = "\n" + job["token"] + json.dumps(report, ensure_ascii=True) + "\n"
    _write_all(1, data.encode("ascii"))
    # os._exit, not a normal exit: it skips waiting for threads the student started and skips
    # atexit handlers the student registered, which could otherwise hang or print after the report.
    os._exit(0)


if __name__ == "__main__":
    main()
