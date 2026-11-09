"""Block a commit that would include a secret from .env. Run it before every commit.

Usage (from anywhere inside the repo):
    uv run python scripts/check_secrets.py            # the staged changes (before every commit)
    uv run python scripts/check_secrets.py --history  # every commit ever (before every push)

Exit code 0: nothing secret found. Exit code 1: a value from an env file (.env, .env~, ...) or
something that looks like a known kind of key is in the checked text, or an env file itself is
staged / was ever committed. --history matters because a deleted file is still in old commits,
and a public repo shows all of them.

It checks your *actual* values, so it works for every key format (Google's newer keys don't start
with "AIza"). It never prints a secret.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MIN_SECRET_CHARS = 8  # shorter values (like "1" or "true") are settings, not secrets
# Known key shapes, caught even without an env file. `\b` keeps "task-..." from matching "sk-".
KEY_PATTERNS = {
    "Google API key (AIza...)": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "OpenAI/OpenRouter key (sk-...)": re.compile(r"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{20,}"),
    "GitHub token (ghp_...)": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_\w{22,})"),
    "Hugging Face token (hf_...)": re.compile(r"\bhf_[A-Za-z0-9]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}


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


def _is_env_file(name: str) -> bool:
    file_name = Path(name).name
    return file_name.startswith(".env") and file_name != ".env.example"


def secret_values(root: Path) -> list[str]:
    """The values of every env file in the repo root (.env, .env~, .env.local, ...)."""
    values = []
    for path in sorted(root.glob(".env*")):
        if path.is_file() and _is_env_file(path.name):
            values.extend(env_values(path))
    return values


def find_problems(
    text: str, file_names: list[str], secrets: list[str], where: str = "the staged changes"
) -> list[str]:
    """What is wrong with `text` (a diff) and `file_names`, described without showing any secret."""
    problems = []
    for name in sorted(set(file_names)):
        if _is_env_file(name):
            problems.append(f"{name} is in {where}: env files must never be committed")
    for number, secret in enumerate(secrets, start=1):
        if secret in text:
            problems.append(f"value number {number} from an env file is in {where}")
    for kind, pattern in KEY_PATTERNS.items():
        if pattern.search(text):
            problems.append(f"something that looks like a {kind} is in {where}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Look for secrets before a commit or a push.")
    parser.add_argument(
        "--history", action="store_true", help="check every commit, not the staged changes"
    )
    args = parser.parse_args(argv)
    root = Path(_git("rev-parse", "--show-toplevel").strip())
    if args.history:
        where = "the git history"
        text = _git("log", "-p", "--all", "--full-history")
        file_names = _git("log", "--all", "--full-history", "--format=", "--name-only").split()
        fix = "Rotate (replace) the leaked key at its provider: a pushed commit can't be unsent."
    else:
        where = "the staged changes"
        text = _git("diff", "--cached")
        file_names = _git("diff", "--cached", "--name-only").split()
        fix = "Unstage it (git restore --staged <file>) and remove the secret first."
    problems = find_problems(text, file_names, secret_values(root), where)
    if problems:
        print("BLOCKED, do not commit or push:")
        for problem in problems:
            print(f"  - {problem}")
        print(fix)
        return 1
    print(f"OK: no secrets in {where}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
