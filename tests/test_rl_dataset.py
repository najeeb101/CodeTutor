"""The RL dataset builder (Week 6 Step 1): module folds, student-view prompts, stable bytes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from codetutor.evals.prompt import PROMPT_VERSION, build_messages
from codetutor.problems import Problem
from codetutor.rl.dataset import (
    FOLDS,
    HELDOUT_FILE,
    MANIFEST_FILE,
    SPLITS_FILE,
    TRAIN_FILE,
    UnknownFoldError,
    build_fold,
    fold_names,
    load_bank_with_hashes,
    load_rows,
    make_row,
    split,
    splits_description,
    stale_rows,
)
from codetutor.tutor.guardrail import solution_lines


@pytest.fixture(scope="module")
def bank() -> list[tuple[Problem, str]]:
    return load_bank_with_hashes()


@pytest.fixture(scope="module")
def problems(bank: list[tuple[Problem, str]]) -> list[Problem]:
    return [problem for problem, _ in bank]


def test_the_folds_hold_out_every_module_exactly_once(problems: list[Problem]) -> None:
    held = sorted(m for modules in FOLDS.values() for m in modules)
    assert held == sorted({p.module for p in problems})


def test_train_and_heldout_are_disjoint_and_cover_the_bank(problems: list[Problem]) -> None:
    for fold in fold_names():
        train, held_out = split(problems, fold)
        assert not {p.id for p in train} & {p.id for p in held_out}
        assert {p.id for p in train} | {p.id for p in held_out} == {p.id for p in problems}
        assert {p.module for p in held_out} == set(FOLDS[fold])
        assert not {p.module for p in train} & set(FOLDS[fold])


def test_every_problem_is_held_out_in_exactly_one_fold(problems: list[Problem]) -> None:
    counts = {p.id: 0 for p in problems}
    for fold in fold_names():
        for p in split(problems, fold)[1]:
            counts[p.id] += 1
    assert set(counts.values()) == {1}


def test_an_unknown_fold_is_refused(problems: list[Problem]) -> None:
    with pytest.raises(UnknownFoldError, match="choose one of a, b, c, d"):
        split(problems, "z")


def test_a_row_is_the_week_2_prompt_of_the_student_view(
    bank: list[tuple[Problem, str]],
) -> None:
    problem, digest = bank[0]
    row = make_row(problem, digest)
    assert row.prompt == build_messages(problem.to_student_view())
    assert (row.problem_id, row.problem_version, row.module) == (
        problem.id,
        problem.version,
        problem.module,
    )
    assert row.prompt_version == PROMPT_VERSION and row.content_hash == digest


def test_rows_never_contain_the_solution_the_hints_or_the_buggy_files(
    bank: list[tuple[Problem, str]],
) -> None:
    for problem, digest in bank:
        row = make_row(problem, digest)
        prompt = "\n".join(message["content"] for message in row.prompt)
        assert problem.solution_code.strip() not in prompt, problem.id
        for line in solution_lines(problem):
            assert " ".join(line.split()) not in " ".join(prompt.split()), (problem.id, line)
        for hint in problem.hints:
            assert hint not in prompt, problem.id
        for code in problem.buggy.values():
            assert code.strip() not in prompt, problem.id


def test_the_files_are_byte_identical_across_two_builds(
    bank: list[tuple[Problem, str]], tmp_path: Path
) -> None:
    first = build_fold(bank, "a", tmp_path / "one")
    second = build_fold(bank, "a", tmp_path / "two")
    for a, b in zip(first, second, strict=True):
        assert a.read_bytes() == b.read_bytes(), a.name
    assert {p.name for p in first} == {TRAIN_FILE, HELDOUT_FILE, MANIFEST_FILE}


def test_the_manifest_matches_the_files(bank: list[tuple[Problem, str]], tmp_path: Path) -> None:
    paths = build_fold(bank, "b", tmp_path)
    folder = paths[0].parent
    manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
    for name in (TRAIN_FILE, HELDOUT_FILE):
        rows = load_rows(folder / name)
        key = "train" if name == TRAIN_FILE else "heldout"
        assert [r.problem_id for r in rows] == manifest[key]["ids"]
        assert manifest[key]["count"] == len(rows)
    assert manifest["heldout_modules"] == [2, 6]


def test_a_changed_problem_makes_its_rows_stale(bank: list[tuple[Problem, str]]) -> None:
    problem, digest = bank[0]
    rows = [make_row(problem, digest)]
    assert stale_rows(rows, bank) == []
    changed = [(problem, "0" * 64), *bank[1:]]
    assert "changed since" in stale_rows(rows, changed)[0]
    assert "no longer in the bank" in stale_rows(rows, bank[1:])[0]


def test_the_committed_split_is_what_the_code_would_write(problems: list[Problem]) -> None:
    committed = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(splits_description(problems)))
