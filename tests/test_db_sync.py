"""Problem sync: folders → problem_versions (sealed copies) + problems (student view)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codetutor.db.models import ProblemRow, ProblemVersionRow
from codetutor.db.sync import SyncError, sync_problems
from codetutor.problems import Problem, StudentProblem, load_all
from conftest import ProblemWriter, valid_meta, valid_tests

PROBLEM_ID = "cs1.loops.sum_of_evens"
OTHER_ID = "cs1.loops.other"


def _sync(session: Session, root: Path) -> Any:
    """Sync and commit, like scripts/sync_problems.py."""
    report = sync_problems(session, root)
    session.commit()
    return report


def _write_meta(folder: Path, **changes: Any) -> None:
    """Rewrite problem.yaml with some fields changed."""
    meta = valid_meta() | changes
    (folder / "problem.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def _change_a_test(folder: Path) -> None:
    """Change one hidden test's input: the kind of change that needs a version bump."""
    tests = valid_tests()
    tests[-1]["input"] = [12]
    tests[-1]["expected"] = 42
    (folder / "tests.yaml").write_text(yaml.safe_dump({"tests": tests}), encoding="utf-8")


def _write_other(write_problem: ProblemWriter) -> Path:
    """A second problem next to the first one (another id and position)."""
    meta = valid_meta() | {"id": OTHER_ID, "order": 2}
    return write_problem(meta=meta, folder="cs1/03_loops/other")


def _versions(session: Session) -> list[tuple[str, int]]:
    rows = session.execute(select(ProblemVersionRow.problem_id, ProblemVersionRow.version))
    return sorted(tuple(row) for row in rows)


def test_first_sync_adds_and_second_sync_changes_nothing(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    root = write_problem().parents[2]

    first = _sync(db_session, root)
    second = _sync(db_session, root)

    assert first.added == [PROBLEM_ID]
    assert (second.added, second.unchanged) == ([], [PROBLEM_ID])
    assert _versions(db_session) == [(PROBLEM_ID, 1)]
    row = db_session.get(ProblemRow, PROBLEM_ID)
    assert (row.version, row.module, row.position, row.active) == (1, 3, 1, True)


def test_changed_files_without_a_version_bump_are_refused(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    folder = write_problem()
    root = folder.parents[2]
    _sync(db_session, root)
    [stored_hash] = db_session.scalars(select(ProblemVersionRow.content_hash)).all()

    _change_a_test(folder)
    with pytest.raises(SyncError, match=r"sum_of_evens: files changed but version is still 1"):
        sync_problems(db_session, root)
    db_session.rollback()

    # Nothing was written: the sealed copy is the old one.
    assert db_session.scalars(select(ProblemVersionRow.content_hash)).all() == [stored_hash]


def test_a_version_bump_keeps_both_copies(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    folder = write_problem()
    root = folder.parents[2]
    _sync(db_session, root)

    _change_a_test(folder)
    _write_meta(folder, version=2)
    report = _sync(db_session, root)

    assert report.updated == [f"{PROBLEM_ID}: v1 -> v2"]
    assert _versions(db_session) == [(PROBLEM_ID, 1), (PROBLEM_ID, 2)]
    assert db_session.get(ProblemRow, PROBLEM_ID).version == 2
    # The old copy still has the old tests, so old submissions can be graded as they were.
    old = db_session.get(ProblemVersionRow, (PROBLEM_ID, 1))
    assert Problem.model_validate(old.problem).tests[-1].input == [11]


def test_versions_only_go_up(db_session: Session, write_problem: ProblemWriter) -> None:
    folder = write_problem(meta=valid_meta() | {"version": 2})
    root = folder.parents[2]
    _sync(db_session, root)

    _write_meta(folder, version=1)
    with pytest.raises(SyncError, match=r"version 1 is lower than the stored version 2"):
        sync_problems(db_session, root)


def test_every_broken_rule_is_reported_at_once(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    first = write_problem()
    second = _write_other(write_problem)
    root = first.parents[2]
    _sync(db_session, root)

    _change_a_test(first)
    _change_a_test(second)
    with pytest.raises(SyncError, match=r"^2 sync rule\(s\) broken") as caught:
        sync_problems(db_session, root)
    assert OTHER_ID in str(caught.value)
    assert PROBLEM_ID in str(caught.value)


def test_a_removed_folder_is_retired_and_can_come_back(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    folder = write_problem()
    _write_other(write_problem)
    root = folder.parents[2]
    _sync(db_session, root)
    backup = root.parent / "backup"  # outside the problems root
    shutil.move(folder, backup)

    report = _sync(db_session, root)
    assert report.retired == [PROBLEM_ID]
    assert db_session.get(ProblemRow, PROBLEM_ID).active is False
    assert _versions(db_session) == [(OTHER_ID, 1), (PROBLEM_ID, 1)]  # kept

    shutil.move(backup, folder)
    report = _sync(db_session, root)
    assert report.restored == [PROBLEM_ID]
    assert db_session.get(ProblemRow, PROBLEM_ID).active is True


def test_an_empty_bank_is_refused(db_session: Session, tmp_path: Path) -> None:
    # A wrong --root must not retire every problem.
    (tmp_path / "problems").mkdir()
    with pytest.raises(SyncError, match="no problems found"):
        sync_problems(db_session, tmp_path / "problems")


def test_the_problems_table_holds_only_the_student_view(
    db_session: Session, write_problem: ProblemWriter
) -> None:
    root = write_problem().parents[2]
    _sync(db_session, root)

    view = db_session.get(ProblemRow, PROBLEM_ID).student_view
    StudentProblem.model_validate(view)  # exactly the student view, no extra keys
    hidden_ids = {test["id"] for test in valid_tests() if test["hidden"]}
    assert {example["id"] for example in view["examples"]}.isdisjoint(hidden_ids)
    assert not {"solution_code", "hints", "buggy", "tests"} & view.keys()


def test_the_whole_bank_survives_the_database_round_trip(db_session: Session) -> None:
    report = _sync(db_session, None)
    db_session.expire_all()  # read back from the database, not from the session's memory

    bank = load_all()
    assert len(report.added) == len(bank) == 33
    for problem in bank:
        copy = db_session.get(ProblemVersionRow, (problem.id, problem.version))
        # repr, not ==: 1 == 1.0 == True in Python, but the grader treats them differently.
        assert repr(Problem.model_validate(copy.problem)) == repr(problem)
        view = db_session.get(ProblemRow, problem.id).student_view
        assert repr(StudentProblem.model_validate(view)) == repr(problem.to_student_view())
    assert db_session.scalar(select(func.count()).select_from(ProblemRow)) == 33
