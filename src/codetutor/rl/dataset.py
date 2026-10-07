"""The RL dataset (Week 6 Step 1): prompts for GRPO training and for the before/after test.

Every row is built from the **student view** of a problem through the Week 2 prompt, so the
solution, the hints, the buggy files and the hidden tests cannot get in. The split is by whole
**module**: a model trained on loops is tested on strings, never on a problem it trained on.
Four folds pair the eight modules so that every problem is held out exactly once.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from codetutor.bank.build import DEFAULT_DIST_DIR, content_hash
from codetutor.evals.prompt import PROMPT_VERSION, build_messages
from codetutor.problems import Problem, find_problem_folders, load_problem

# The only place the split is defined: fold name -> the modules that are held out.
FOLDS: dict[str, tuple[int, ...]] = {"a": (1, 5), "b": (2, 6), "c": (3, 7), "d": (4, 8)}
RL_DIR = DEFAULT_DIST_DIR / "rl"
SPLITS_FILE = Path(__file__).resolve().parents[3] / "lab" / "rl" / "splits.json"
TRAIN_FILE = "train.jsonl"
HELDOUT_FILE = "heldout.jsonl"
MANIFEST_FILE = "manifest.json"


class UnknownFoldError(ValueError):
    """The fold name is not one of `FOLDS`."""


class RlRow(BaseModel):
    """One prompt. `prompt` is the chat the model sees; the other columns go to the reward."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: list[dict[str, str]]
    problem_id: str
    problem_version: int
    module: int
    content_hash: str
    prompt_version: str


def fold_names() -> list[str]:
    """The fold names, in order."""
    return sorted(FOLDS)


def split(problems: Sequence[Problem], fold: str) -> tuple[list[Problem], list[Problem]]:
    """(training problems, held-out problems) for `fold`, each sorted by problem id.

    Whole modules only: a problem is held out exactly when its module is.
    """
    if fold not in FOLDS:
        raise UnknownFoldError(f"unknown fold {fold!r}; choose one of {', '.join(fold_names())}")
    held_modules = set(FOLDS[fold])
    ordered = sorted(problems, key=lambda p: p.id)
    train = [p for p in ordered if p.module not in held_modules]
    held_out = [p for p in ordered if p.module in held_modules]
    return train, held_out


def load_bank_with_hashes(root: Path | None = None) -> list[tuple[Problem, str]]:
    """Every problem with its content hash (the same hash as `dist/problems.jsonl`)."""
    return [(load_problem(folder), content_hash(folder)) for folder in find_problem_folders(root)]


def make_row(problem: Problem, digest: str) -> RlRow:
    """The row for one problem: the Week 2 prompt of its student view."""
    return RlRow(
        prompt=build_messages(problem.to_student_view()),
        problem_id=problem.id,
        problem_version=problem.version,
        module=problem.module,
        content_hash=digest,
        prompt_version=PROMPT_VERSION,
    )


def _jsonl(rows: Sequence[RlRow]) -> str:
    return "".join(
        json.dumps(r.model_dump(), sort_keys=True, ensure_ascii=False) + "\n" for r in rows
    )


def splits_description(bank: Sequence[Problem]) -> dict[str, dict[str, object]]:
    """The committed split: per fold, the held-out modules and the problem ids on each side."""
    result: dict[str, dict[str, object]] = {}
    for fold in fold_names():
        train, held_out = split(bank, fold)
        result[fold] = {
            "heldout_modules": list(FOLDS[fold]),
            "train": [p.id for p in train],
            "heldout": [p.id for p in held_out],
        }
    return result


def write_splits(bank: Sequence[Problem], path: Path = SPLITS_FILE) -> Path:
    """Write the split description (committed, so a changed bank can't move a problem)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(splits_description(bank), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def build_fold(
    bank: Sequence[tuple[Problem, str]], fold: str, out_dir: Path = RL_DIR
) -> list[Path]:
    """Write `<out_dir>/fold-<fold>/{train,heldout}.jsonl` and `manifest.json`.

    Byte-identical for the same bank: rows sorted by id, keys sorted, no clock, no git commit.
    """
    hashes = {problem.id: digest for problem, digest in bank}
    train, held_out = split([problem for problem, _ in bank], fold)
    folder = out_dir / f"fold-{fold}"
    folder.mkdir(parents=True, exist_ok=True)
    texts = {
        TRAIN_FILE: _jsonl([make_row(p, hashes[p.id]) for p in train]),
        HELDOUT_FILE: _jsonl([make_row(p, hashes[p.id]) for p in held_out]),
    }
    manifest = {
        "fold": fold,
        "heldout_modules": list(FOLDS[fold]),
        "prompt_version": PROMPT_VERSION,
        "train": {"count": len(train), "ids": [p.id for p in train]},
        "heldout": {"count": len(held_out), "ids": [p.id for p in held_out]},
        "sha256": {
            name: hashlib.sha256(t.encode("utf-8")).hexdigest() for name, t in texts.items()
        },
    }
    paths = []
    for name, text in texts.items():
        (folder / name).write_text(text, encoding="utf-8")
        paths.append(folder / name)
    manifest_path = folder / MANIFEST_FILE
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return [*paths, manifest_path]


def load_rows(path: Path) -> list[RlRow]:
    """Read a dataset file back."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [RlRow.model_validate_json(line) for line in lines if line.strip()]


def stale_rows(rows: Sequence[RlRow], bank: Sequence[tuple[Problem, str]]) -> list[str]:
    """Messages for rows whose problem changed (or vanished) since the dataset was built."""
    current = {problem.id: (problem.version, digest) for problem, digest in bank}
    messages = []
    for row in rows:
        if row.problem_id not in current:
            messages.append(f"{row.problem_id}: no longer in the bank")
        elif current[row.problem_id] != (row.problem_version, row.content_hash):
            messages.append(f"{row.problem_id}: changed since the dataset was built")
    return messages
