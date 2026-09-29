"""Validate every problem in the bank and print a report. Exit code 1 if any problem is invalid.

Usage:
    python scripts/validate_problems.py
    python scripts/validate_problems.py --root path/to/problems
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codetutor.bank.validate import format_report, validate_bank


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="problems folder")
    args = parser.parse_args()

    bank = validate_bank(args.root)
    print(format_report(bank))
    return 0 if bank.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
