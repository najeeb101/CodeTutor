"""Fill (or check) the expected values in tests.yaml by running each problem's solution.py.

Usage:
    python scripts/fill_expected.py problems/cs1/03_loops/sum_of_evens
    python scripts/fill_expected.py --all
    python scripts/fill_expected.py --all --check     # change nothing; fail if anything differs
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codetutor.bank.expected import ExpectedError, check_expected, fill_expected
from codetutor.problems import ProblemError, find_problem_folders, load_problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="*", type=Path, help="problem folders")
    parser.add_argument("--all", action="store_true", help="every problem under problems/")
    parser.add_argument("--check", action="store_true", help="only check, don't write")
    args = parser.parse_args()

    folders = find_problem_folders() if args.all else args.folders
    if not folders:
        parser.error("give one or more problem folders, or --all")

    failures = 0
    for folder in folders:
        try:
            if args.check:
                messages = check_expected(load_problem(folder, require_expected=False))
                if messages:
                    failures += 1
                    print(f"❌ {folder}")
                    for message in messages:
                        print(f"     {message}")
                else:
                    print(f"✅ {folder}")
            else:
                problem, changed = fill_expected(folder)
                count = len(problem.tests)
                print(f"✅ {problem.id}: {count} tests, {changed} expected values changed")
        except (ExpectedError, ProblemError) as exc:
            failures += 1
            print(f"❌ {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
