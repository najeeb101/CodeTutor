"""Build the dataset files that evals (Week 2) and RL training (Weeks 6-7) read.

The problem folders are the human-editable source; dist/*.jsonl is the machine-friendly build
output (one JSON object per line, one line per problem). It is generated, so it is not in git.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from codetutor.problems import find_problem_folders, load_problem

DEFAULT_DIST_DIR = Path(__file__).resolve().parents[3] / "dist"
FULL_FILE = "problems.jsonl"
STUDENT_FILE = "problems_student.jsonl"

# Only these files define a problem. Using a fixed list (not "every file in the folder") means
# junk like __pycache__ or editor backups can never change the hash.
PROBLEM_FILES = ("problem.yaml", "tests.yaml", "starter.py", "solution.py")


def hashed_files(folder: Path) -> list[Path]:
    """The files that make up one problem, in a fixed order (buggy files sorted by name)."""
    folder = Path(folder)
    return [folder / name for name in PROBLEM_FILES] + sorted((folder / "buggy").glob("*.py"))


def content_hash(folder: Path) -> str:
    """Return the sha256 hex digest of all files in `hashed_files(folder)`.

    Same files → same hash, on every machine. Any change to any file → a different hash.
    """
    folder = Path(folder)
    digest = hashlib.sha256()
    for path in hashed_files(folder):
        name = path.relative_to(folder).as_posix()  # "/" on every OS, e.g. "buggy/off_by_one.py"
        data = path.read_bytes()  # bytes, not text: no newline or encoding conversion
        # name, then the data length, then the data. The b"\0" separators and the length make
        # the boundaries clear, so "ab" + "c" and "a" + "bc" can never give the same bytes.
        digest.update(name.encode("utf-8") + b"\0" + str(len(data)).encode("ascii") + b"\0")
        digest.update(data)
    return digest.hexdigest()


def _json_line(record: dict[str, Any]) -> str:
    """One record as one line of JSON. sort_keys makes the output byte-for-byte deterministic."""
    return json.dumps(record, sort_keys=True, ensure_ascii=False)


def build_dataset(root: Path | None = None, dist_dir: Path | None = None) -> list[Path]:
    """Write problems.jsonl (internal view) and problems_student.jsonl. Returns the two paths.

    Raises ProblemError if any problem fails to load (run the validator first for a full report).
    """
    dist_dir = DEFAULT_DIST_DIR if dist_dir is None else Path(dist_dir)
    full_lines: list[str] = []
    student_lines: list[str] = []
    for folder in find_problem_folders(root):
        problem = load_problem(folder)
        digest = content_hash(folder)
        full_lines.append(_json_line({**problem.model_dump(mode="json"), "content_hash": digest}))
        student = problem.to_student_view().model_dump(mode="json")
        student_lines.append(_json_line({**student, "content_hash": digest}))

    dist_dir.mkdir(parents=True, exist_ok=True)
    full_path = dist_dir / FULL_FILE
    student_path = dist_dir / STUDENT_FILE
    full_path.write_text("".join(line + "\n" for line in full_lines), encoding="utf-8")
    student_path.write_text("".join(line + "\n" for line in student_lines), encoding="utf-8")
    return [full_path, student_path]
