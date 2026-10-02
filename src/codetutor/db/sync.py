"""Copy the problem folders into Postgres. The files stay the source of truth (docs/database.md).

Rules:
1. A new (id, version): store a sealed copy in `problem_versions`; `problems` points to it.
2. A stored (id, version) whose files changed: refuse. Bump `version` in problem.yaml.
3. Versions only go up.
4. A problem whose folder is gone: `active = false`. Never deleted (submissions point to it).

Every rule is checked before anything is written, and the caller commits, so a sync is all or
nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codetutor.bank.build import content_hash
from codetutor.db.models import ProblemRow, ProblemVersionRow
from codetutor.problems import Problem, find_problem_folders, load_all, load_problem


class SyncError(Exception):
    """The problem files break a sync rule. Nothing was written."""


@dataclass
class SyncReport:
    """What a sync changed. Each list holds problem ids, sorted."""

    added: list[str] = field(default_factory=list)  # new problems
    updated: list[str] = field(default_factory=list)  # "id: v1 -> v2"
    restored: list[str] = field(default_factory=list)  # folder came back, active again
    unchanged: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)  # folder gone, now inactive


def _read_bank(root: Path | None) -> list[tuple[Problem, str]]:
    """Every problem in the folders, with its content hash."""
    # load_all runs the bank-wide checks (duplicate ids or positions). Each folder is then
    # read once more to pair it with its hash: ~0.1 s, and it keeps one loader for everything.
    load_all(root)
    return [(load_problem(folder), content_hash(folder)) for folder in find_problem_folders(root)]


def _rule_violations(
    bank: list[tuple[Problem, str]],
    stored_hashes: dict[tuple[str, int], str],
    current: dict[str, ProblemRow],
) -> list[str]:
    """One message per problem that breaks rule 2 or 3."""
    problems = []
    for problem, digest in bank:
        stored = stored_hashes.get((problem.id, problem.version))
        if stored is not None and stored != digest:
            problems.append(
                f"{problem.id}: files changed but version is still {problem.version} "
                "(bump `version` in problem.yaml)"
            )
        row = current.get(problem.id)
        if row is not None and problem.version < row.version:
            problems.append(
                f"{problem.id}: version {problem.version} is lower than the stored "
                f"version {row.version} (versions only go up)"
            )
    return problems


def _catalog_values(problem: Problem) -> dict[str, object]:
    """The `problems` columns for this problem: its student view, never hidden tests."""
    return {
        "version": problem.version,
        "module": problem.module,
        "position": problem.order,
        "title": problem.title,
        "difficulty": problem.difficulty.value,
        "active": True,
        "student_view": problem.to_student_view().model_dump(mode="json"),
        "updated_at": func.now(),
    }


def _update(row: ProblemRow, values: dict[str, object]) -> None:
    """Set several columns of an ORM row."""
    for name, value in values.items():
        setattr(row, name, value)


def sync_problems(session: Session, root: Path | None = None) -> SyncReport:
    """Bring the database in line with the problem folders under `root` (default: the bank).

    The caller commits. Raises SyncError (before writing anything) if a rule is broken, and
    ProblemError if a problem folder is invalid.
    """
    bank = _read_bank(root)
    if not bank:
        # A wrong --root would otherwise retire every problem.
        raise SyncError(
            f"no problems found under {root or 'the default bank'}; nothing was written"
        )
    stored_hashes = {
        (problem_id, version): digest
        for problem_id, version, digest in session.execute(
            select(
                ProblemVersionRow.problem_id,
                ProblemVersionRow.version,
                ProblemVersionRow.content_hash,
            )
        )
    }
    current = {row.id: row for row in session.scalars(select(ProblemRow))}

    violations = _rule_violations(bank, stored_hashes, current)
    if violations:
        raise SyncError(
            f"{len(violations)} sync rule(s) broken, nothing was written:\n  "
            + "\n  ".join(violations)
        )

    # Rule 1, part one: sealed copies of new versions. Flushed first, because `problems`
    # rows point to them (foreign key).
    for problem, digest in bank:
        if (problem.id, problem.version) not in stored_hashes:
            session.add(
                ProblemVersionRow(
                    problem_id=problem.id,
                    version=problem.version,
                    content_hash=digest,
                    problem=problem.model_dump(mode="json"),
                )
            )
    session.flush()

    # Rule 1, part two: the `problems` rows (what students see).
    report = SyncReport()
    for problem, _digest in bank:
        row = current.get(problem.id)
        if row is None:
            session.add(ProblemRow(id=problem.id, **_catalog_values(problem)))
            report.added.append(problem.id)
        elif row.version != problem.version:
            report.updated.append(f"{problem.id}: v{row.version} -> v{problem.version}")
            _update(row, _catalog_values(problem))
        elif not row.active:
            report.restored.append(problem.id)
            _update(row, _catalog_values(problem))
        else:
            report.unchanged.append(problem.id)

    # Rule 4: problems whose folder is gone.
    in_files = {problem.id for problem, _digest in bank}
    for problem_id, row in current.items():
        if problem_id not in in_files and row.active:
            _update(row, {"active": False, "updated_at": func.now()})
            report.retired.append(problem_id)

    session.flush()
    for ids in (report.added, report.updated, report.restored, report.unchanged, report.retired):
        ids.sort()
    return report
