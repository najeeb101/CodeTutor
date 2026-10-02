"""Check the running app end to end: API, worker and web UI (make e2e).

Start the stack first (three terminals): `make worker`, `make api`, `make web`. Then:
    python scripts/e2e_check.py                       # API + web UI, problem cs1.loops.fizzbuzz
    python scripts/e2e_check.py --no-web              # API + worker only
    python scripts/e2e_check.py --problem cs1.dicts.two_sum

Each run logs in as a new user (e2e-<time>) and submits two answers: the problem's reference
solution (must be accepted) and its first buggy solution (must fail, hidden tests hidden).
"""

from __future__ import annotations

import argparse

from codetutor.e2e import RESULT_TIMEOUT_S, run_checks
from codetutor.problems import ProblemNotFoundError, get_problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="API address")
    parser.add_argument("--web", default="http://127.0.0.1:3100", help="web UI address")
    parser.add_argument("--no-web", action="store_true", help="check the API and worker only")
    parser.add_argument("--problem", default="cs1.loops.fizzbuzz", help="problem id")
    parser.add_argument(
        "--timeout", type=float, default=RESULT_TIMEOUT_S, help="seconds to wait for a result"
    )
    args = parser.parse_args()

    try:
        problem = get_problem(args.problem)
    except ProblemNotFoundError as exc:
        print(f"❌ {exc}")
        return 1
    checks = run_checks(
        args.api,
        problem,
        web_url=None if args.no_web else args.web,
        result_timeout_s=args.timeout,
    )
    for check in checks:
        mark = "✅" if check.ok else "❌"
        print(f"{mark} {check.name:<48} {check.seconds:5.1f} s  {check.detail}")
    if all(check.ok for check in checks):
        print(f"All {len(checks)} checks passed.")
        return 0
    print("Stopped at the first failed check.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
