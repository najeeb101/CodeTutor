"""Tests for scripts/check_secrets.py, run as a real script in a throwaway git repository."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
FAKE_SECRET = "AQ.fake_secret_value_for_tests_123"  # new-style key shape, not "AIza..."


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """An empty git repo with a .env holding one fake secret."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".env").write_text(f"# comment\nGEMINI_API_KEY={FAKE_SECRET}\nDEBUG=1\n")
    return tmp_path


def _stage(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "-f", name], check=True)


def _check(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=repo, capture_output=True, text=True, check=False
    )


def test_clean_changes_pass(repo: Path) -> None:
    _stage(repo, "notes.txt", "nothing secret here\n")
    result = _check(repo)
    assert result.returncode == 0, result.stdout
    assert "OK" in result.stdout


def test_a_staged_env_value_is_blocked_and_never_printed(repo: Path) -> None:
    _stage(repo, "config.py", f'KEY = "{FAKE_SECRET}"\n')
    result = _check(repo)
    assert result.returncode == 1
    assert "BLOCKED" in result.stdout
    assert FAKE_SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize("name", [".env.local", ".env~"])
def test_a_staged_env_file_is_blocked(repo: Path, name: str) -> None:
    _stage(repo, name, "OTHER=short\n")
    result = _check(repo)
    assert result.returncode == 1
    assert f"{name} is staged" in result.stdout


def test_the_env_example_template_is_allowed(repo: Path) -> None:
    _stage(repo, ".env.example", "GEMINI_API_KEY=\n")
    assert _check(repo).returncode == 0


def test_a_classic_google_key_is_blocked_even_without_env(repo: Path) -> None:
    (repo / ".env").unlink()
    _stage(repo, "leak.txt", "AIza" + "x" * 35 + "\n")
    assert _check(repo).returncode == 1
