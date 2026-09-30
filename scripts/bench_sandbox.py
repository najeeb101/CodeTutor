"""Measure how long one grading takes with each sandbox (the price of Docker's safety).

Usage:
    python scripts/bench_sandbox.py
    python scripts/bench_sandbox.py --runs 50 --problem cs1.loops.fizzbuzz
"""

from __future__ import annotations

import argparse
import math
import statistics
import time

from codetutor.grader import (
    DockerSandbox,
    GradeStatus,
    Sandbox,
    SandboxUnavailableError,
    SubprocessSandbox,
    grade,
)
from codetutor.problems import Problem, ProblemError, get_problem


def _time_one(problem: Problem, sandbox: Sandbox) -> float:
    """Grade the reference solution once; return the time in milliseconds."""
    start = time.perf_counter()
    result = grade(problem, problem.solution_code, sandbox=sandbox)
    elapsed_ms = (time.perf_counter() - start) * 1000
    if result.status != GradeStatus.ACCEPTED:
        raise SystemExit(f"the reference solution was not accepted: {result.status}")
    return elapsed_ms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--problem", default="cs1.loops.fizzbuzz", help="problem id")
    parser.add_argument("--runs", type=int, default=20, help="timed runs per sandbox")
    args = parser.parse_args()

    try:
        problem = get_problem(args.problem)
        docker = DockerSandbox()
        sandboxes: dict[str, Sandbox] = {"subprocess": SubprocessSandbox(), "docker": docker}
    except (ProblemError, SandboxUnavailableError) as exc:
        parser.error(str(exc))

    print(f"{problem.id}: {len(problem.tests)} tests, {args.runs} runs per sandbox, one at a time")
    medians = {}
    for name, sandbox in sandboxes.items():
        first = _time_one(problem, sandbox)  # the first run can be slower (cold caches)
        times = sorted(_time_one(problem, sandbox) for _ in range(args.runs))
        p90 = times[math.ceil(0.9 * len(times)) - 1]
        medians[name] = statistics.median(times)
        print(
            f"  {name:<10} first {first:5.0f} ms | median {medians[name]:5.0f} ms"
            f" | p90 {p90:5.0f} ms | max {times[-1]:5.0f} ms"
        )
    extra = medians["docker"] - medians["subprocess"]
    ratio = medians["docker"] / medians["subprocess"]
    print(f"Docker adds {extra:.0f} ms per submission (median), {ratio:.0f}x slower.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
