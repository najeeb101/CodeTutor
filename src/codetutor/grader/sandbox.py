"""Sandboxes run the runner (and so the student code) in a separate, limited process.

`Sandbox` is a small interface, so `grade()` works the same with either backend:
- `SubprocessSandbox`: a child process with resource limits. Fast, but NOT secure: student code
  can still read any file your user can read and use the network.
- `DockerSandbox`: the same runner inside a locked-down container (no network, no host files,
  process limit, non-root). Slower to start, and much safer.
See docs/grader.md (threat model). Use Docker before strangers submit code.
"""

from __future__ import annotations

import os
import secrets
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

# --- Docker settings ---
# Pinned by digest, not only by tag: a tag like 3.12-slim moves to newer builds, a digest never
# changes, so every run grades with exactly the same Python (deterministic grading).
DOCKER_IMAGE = (
    "python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
)
# Starting a container takes time the student must not pay for. Measured on WSL2 + Docker Desktop:
# median 0.73 s, max 1.2 s with 4 containers starting in parallel. 5 s leaves a wide margin.
DOCKER_START_MARGIN_S = 5.0
# Memory limit of the container, above the runner's own limit (RLIMIT_AS): the runner's clean
# MemoryError should come first; the container limit is only the backstop.
DOCKER_MEMORY_MARGIN_MB = 64
# Scratch space in /tmp, a bit more than the file-size limit, so the runner's "File too large"
# comes before "No space left on device".
DOCKER_TMPFS_MARGIN_MB = 8
DOCKER_PIDS_LIMIT = 64
DOCKER_LABEL = "codetutor.sandbox=1"  # lets tests check that no container is left behind
DOCKER_RUNNER_PATH = "/sandbox/runner.py"
DOCKER_NOBODY = "65534:65534"  # the "nobody" user and group
DOCKER_CLI_TIMEOUT_S = 30.0  # for our own short docker commands (inspect, kill)


class SandboxUnavailableError(RuntimeError):
    """The sandbox can't run at all (e.g. Docker is not running). Not the submission's fault."""


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


def _run_captured(
    argv: list[str],
    job: SandboxJob,
    timeout_s: float,
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    stop_extra: Callable[[], None] | None = None,
) -> RawResult:
    """Start `argv` in its own process group, send it the job, and collect its capped output.

    Shared by both sandboxes. On a timeout or too much output, `stop_extra()` runs first (Docker:
    stop the container, because killing the `docker` client alone does not), then the process
    group is killed.
    """
    start = time.perf_counter()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,  # own session + process group, so killpg gets everything
        close_fds=True,
    )
    # With start_new_session the child is the group leader, so its pid is the group id.
    pgid = process.pid

    def stop() -> None:
        if stop_extra is not None:
            stop_extra()
        _kill_process_group(pgid)

    stdout = _CappedReader(process.stdout, MAX_CHILD_STDOUT_BYTES, stop)
    stderr = _CappedReader(process.stderr, MAX_CHILD_STDERR_BYTES, stop)
    stdout.start()
    stderr.start()

    try:
        process.stdin.write(job.model_dump_json().encode("utf-8"))
        process.stdin.close()
    except BrokenPipeError:
        pass  # the child died before reading its job; reported as a crash below

    timed_out = False
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop()

    # Always kill the group, even after a normal exit: this removes any processes the
    # student code started (e.g. a subprocess that sleeps forever).
    _kill_process_group(pgid)
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


class SubprocessSandbox:
    """Runs the runner in a child process with resource limits (POSIX only). NOT secure."""

    def run(self, job: SandboxJob) -> RawResult:
        """Run the job in a fresh child process and return what happened."""
        with tempfile.TemporaryDirectory(prefix="codetutor-", ignore_cleanup_errors=True) as work:
            argv = [sys.executable, *PYTHON_FLAGS, str(RUNNER_PATH)]
            return _run_captured(argv, job, job.total_timeout_s, cwd=work, env=CHILD_ENV)


def _docker_kill(name: str) -> None:
    """Stop a container. Fine if it is already gone."""
    try:
        subprocess.run(["docker", "kill", name], capture_output=True, timeout=DOCKER_CLI_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass  # Docker itself is stuck; the tests' leftover-container check would show it


def _signal_returncode(returncode: int | None) -> int | None:
    """Docker reports "killed by signal N" as exit code 128 + N; turn it into -N like Popen does.

    A student's os._exit(137) looks the same. That's harmless: without a result it is a crash
    either way, only the message differs. Numbers that are not real signals stay unchanged.
    """
    if returncode is None or returncode <= 128:
        return returncode
    try:
        return -signal.Signals(returncode - 128).value
    except ValueError:
        return returncode


class DockerSandbox:
    """Runs the same runner inside a locked-down Docker container.

    Closes the holes of SubprocessSandbox: no network, no access to the host's files, a process
    limit, and nothing survives the container. Still not perfect: a container shares the host's
    kernel (docs/grader.md, threat model).
    """

    def __init__(self, image: str = DOCKER_IMAGE) -> None:
        self.image = image
        self._check_available()

    def _check_available(self) -> None:
        """Fail early and clearly if Docker or the image is missing, instead of letting every
        submission "crash" with reward 0."""
        try:
            check = subprocess.run(
                ["docker", "image", "inspect", self.image],
                capture_output=True,
                text=True,
                timeout=DOCKER_CLI_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SandboxUnavailableError(f"cannot run docker: {exc}") from exc
        if check.returncode != 0:
            reason = check.stderr.strip().splitlines()[-1] if check.stderr.strip() else "unknown"
            raise SandboxUnavailableError(
                f"Docker image not available ({reason}). Is Docker running, and is your user "
                f"in the docker group? Then run: docker pull {self.image}"
            )

    def command(self, job: SandboxJob, name: str) -> list[str]:
        """The `docker run` command for one job. Each option blocks one kind of attack."""
        memory = f"{job.memory_mb + DOCKER_MEMORY_MARGIN_MB}m"
        scratch = f"/tmp:size={job.max_file_mb + DOCKER_TMPFS_MARGIN_MB}m"
        argv = ["docker", "run", "--rm", "-i"]  # remove when done; the job arrives on stdin
        # A tiny init process becomes PID 1. As PID 1 the runner would ignore signals it has no
        # handler for, like SIGXCPU from its CPU limit (measured: the label then flipped between
        # timeout and crashed from run to run).
        argv += ["--init"]
        argv += ["--name", name]  # so we can stop it: killing the docker client does not
        argv += ["--label", DOCKER_LABEL]
        argv += ["--network", "none"]  # no network at all
        argv += ["--read-only", "--tmpfs", scratch]  # image files can't change; small /tmp only
        argv += ["--workdir", "/tmp"]
        argv += ["--user", DOCKER_NOBODY]  # not root inside the container
        argv += ["--cap-drop", "ALL"]  # no special kernel permissions
        argv += ["--security-opt", "no-new-privileges"]  # can't gain any later (setuid files)
        argv += ["--pids-limit", str(DOCKER_PIDS_LIMIT)]  # stops fork bombs
        argv += ["--memory", memory, "--memory-swap", memory]  # hard memory limit, no swap
        argv += ["--cpus", "1"]
        argv += ["--env", f"PYTHONHASHSEED={CHILD_ENV['PYTHONHASHSEED']}"]
        # Only the runner is shared with the container, read-only. No other host file is visible.
        argv += ["--mount", f"type=bind,src={RUNNER_PATH},dst={DOCKER_RUNNER_PATH},readonly"]
        return [*argv, self.image, "python", *PYTHON_FLAGS, DOCKER_RUNNER_PATH]

    def run(self, job: SandboxJob) -> RawResult:
        """Run the job in a fresh container and return what happened."""
        name = f"codetutor-{secrets.token_hex(6)}"
        raw = _run_captured(
            self.command(job, name),
            job,
            job.total_timeout_s + DOCKER_START_MARGIN_S,
            stop_extra=lambda: _docker_kill(name),
        )
        returncode = _signal_returncode(raw.returncode)
        # Our wall-clock timer has the start-up margin, so code that keeps the CPU busy usually
        # hits the runner's CPU limit first (SIGXCPU). That limit is a total time limit too, and
        # it doesn't count container start-up, so report it as a timeout.
        timed_out = raw.timed_out or returncode == -signal.SIGXCPU
        return raw.model_copy(update={"returncode": returncode, "timed_out": timed_out})
