"""Sandboxes run the runner (and so the student code) in a separate, limited process.

`Sandbox` is a small interface so a Docker-based sandbox can replace the subprocess one later
without changing `grade()`.

WARNING: `SubprocessSandbox` is NOT a secure sandbox. It limits time, memory, file size and output,
but student code can still read any file your user can read and use the network.
See docs/grader.md (threat model). Use Docker before strangers submit code.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Protocol

from codetutor.grader.models import (
    MAX_CHILD_STDERR_BYTES,
    MAX_CHILD_STDOUT_BYTES,
    RawResult,
    SandboxJob,
)

RUNNER_PATH = Path(__file__).with_name("runner.py")

# -S: don't load `site` (no site-packages: student code can't import the venv's packages, and
#     startup is faster). -s: no user site-packages. -P: don't add the runner's folder to sys.path.
# We don't use -I: it ignores PYTHONHASHSEED, and then set/dict-of-str ordering changes between
# runs, which breaks deterministic grading. Since we pass our own tiny env, -I's other job
# (ignoring PYTHON* variables from the user's environment) isn't needed.
PYTHON_FLAGS = ("-S", "-s", "-P")
CHILD_ENV = {"PYTHONHASHSEED": "0"}

# How long to wait for the output readers after the child is gone. A grandchild that escaped the
# process group (setsid) could keep the pipes open forever; we stop waiting instead of hanging.
READER_JOIN_TIMEOUT_S = 2.0


class Sandbox(Protocol):
    """Anything that can run a SandboxJob and report what happened."""

    def run(self, job: SandboxJob) -> RawResult:
        """Run the job and return the raw observations."""
        ...


class _CappedReader(threading.Thread):
    """Reads a pipe in the background, keeping at most `limit` bytes.

    Reading must happen in parallel with the child running: if nobody reads, a full pipe blocks
    the child. Past the limit it calls `on_overflow` (which kills the child) and discards the rest.
    """

    def __init__(self, pipe: IO[bytes], limit: int, on_overflow: Callable[[], None]) -> None:
        super().__init__(daemon=True)
        self._pipe = pipe
        self._limit = limit
        self._on_overflow = on_overflow
        self._chunks: list[bytes] = []
        self._size = 0
        self.overflow = False

    def run(self) -> None:
        while chunk := self._pipe.read1(65536):
            if self._size + len(chunk) > self._limit:
                if not self.overflow:
                    self.overflow = True
                    self._on_overflow()
                continue
            self._chunks.append(chunk)
            self._size += len(chunk)

    def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8", errors="replace")


def _kill_process_group(pgid: int) -> None:
    """Kill every process in the group. Fine if they are already gone."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class SubprocessSandbox:
    """Runs the runner in a child process with resource limits (POSIX only)."""

    def run(self, job: SandboxJob) -> RawResult:
        """Run the job in a fresh child process and return what happened."""
        start = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="codetutor-", ignore_cleanup_errors=True) as work:
            process = subprocess.Popen(
                [sys.executable, *PYTHON_FLAGS, str(RUNNER_PATH)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work,
                env=CHILD_ENV,
                start_new_session=True,  # own session + process group, so killpg gets everything
                close_fds=True,
            )
            # With start_new_session the child is the group leader, so its pid is the group id.
            pgid = process.pid

            def kill() -> None:
                _kill_process_group(pgid)

            stdout = _CappedReader(process.stdout, MAX_CHILD_STDOUT_BYTES, kill)
            stderr = _CappedReader(process.stderr, MAX_CHILD_STDERR_BYTES, kill)
            stdout.start()
            stderr.start()

            try:
                process.stdin.write(job.model_dump_json().encode("utf-8"))
                process.stdin.close()
            except BrokenPipeError:
                pass  # the child died before reading its job; reported as a crash below

            timed_out = False
            try:
                process.wait(timeout=job.total_timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True

            # Always kill the group, even after a normal exit: this removes any processes the
            # student code started (e.g. a subprocess that sleeps forever).
            kill()
            process.wait()
            stdout.join(READER_JOIN_TIMEOUT_S)
            stderr.join(READER_JOIN_TIMEOUT_S)

        return RawResult(
            returncode=process.returncode,
            stdout=stdout.text(),
            stderr=stderr.text(),
            timed_out=timed_out,
            output_overflow=stdout.overflow or stderr.overflow,
            duration_ms=round((time.perf_counter() - start) * 1000, 3),
        )
