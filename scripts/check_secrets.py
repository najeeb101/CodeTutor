"""Block a commit that would include a secret from .env. Run it before every commit.

Usage (from anywhere inside the repo):
    uv run python scripts/check_secrets.py

Exit code 0: nothing secret is staged. Exit code 1: a value from .env (or something that looks
like a Google API key) is in the staged changes, or an env file itself is staged.

It checks your *actual* values, so it works for every key format (Google's newer keys don't start
with "AIza"). It never prints a secret.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MIN_SECRET_CHARS = 8  # shorter values (like "1" or "true") are settings, not secrets
KEY_PATTERNS = [re.compile(r"AIza[0-9A-Za-z_-]{35}")]  # classic Google API keys, even without .env


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def env_values(path: Path) -> list[str]:
    """The non-empty values in a .env file (quotes removed), skipping comments and short ones."""
    if not path.exists():
        return []
    values = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.partition("=")[2].strip().strip("\"'")
        if len(value) >= MIN_SECRET_CHARS:
            values.append(value)
    return values


def find_problems(staged_diff: str, staged_files: list[str], secrets: list[str]) -> list[str]:
    """What is wrong with the staged changes, described without showing any secret."""
    problems = []
    for name in staged_files:
        file_name = Path(name).name
        if file_name.startswith(".env") and file_name != ".env.example":
            problems.append(f"{name} is staged: env files must never be committed")
    for number, secret in enumerate(secrets, start=1):
        if secret in staged_diff:
            problems.append(f"value number {number} from .env is in the staged changes")
    for pattern in KEY_PATTERNS:
        if pattern.search(staged_diff):
            problems.append("something that looks like a Google API key (AIza...) is staged")
    return problems


def main() -> int:
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    staged_diff = _git("diff", "--cached")
    staged_files = _git("diff", "--cached", "--name-only").split()
    problems = find_problems(staged_diff, staged_files, env_values(root / ".env"))
    if problems:
        print("BLOCKED, do not commit:")
        for problem in problems:
            print(f"  - {problem}")
        print("Unstage it (git restore --staged <file>) and remove the secret first.")
        return 1
    print("OK: no secrets in the staged changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
