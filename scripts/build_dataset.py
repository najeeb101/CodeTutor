"""Build dist/problems.jsonl (internal view) and dist/problems_student.jsonl (student view).

Usage:
    python scripts/build_dataset.py
    python scripts/build_dataset.py --root path/to/problems --out path/to/dist
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codetutor.bank.build import build_dataset
from codetutor.problems import ProblemError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="problems folder")
    parser.add_argument("--out", type=Path, default=None, help="output folder (default: dist/)")
    args = parser.parse_args()

    try:
        paths = build_dataset(args.root, args.out)
    except ProblemError as exc:
        print(f"❌ {exc}\n   Run scripts/validate_problems.py for a full report.")
        return 1
    for path in paths:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        print(f"✅ {path}: {lines} problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
