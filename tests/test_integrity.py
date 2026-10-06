"""The integrity checks (Week 5 Step 2b): rename-proof comparison, the four signals, the flags
table and the batch job's database side. See docs/integrity.md §2."""

from __future__ import annotations

import ast
import random
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from codetutor.db.models import IntegrityFlagRow, SubmissionRow
from codetutor.db.sync import sync_problems
from codetutor.db.users import get_or_create_user
from codetutor.integrity.known_ai import known_ai_answers
from codetutor.integrity.normalize import canonical, fingerprints, similarity
from codetutor.integrity.signals import (
    INTEGRITY_VERSION,
    FlagKind,
    IntegrityConfig,
    KnownAnswer,
    SubmissionInfo,
    detect,
    needs_review,
)
from codetutor.integrity.store import load_submissions, replace_flags
from codetutor.problems.loader import load_all
from codetutor.sim.personas import CohortConfig
from codetutor.sim.transforms import reformat, rename_identifiers
from codetutor.worker.jobs import enqueue_submission

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "codetutor"
START = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)

LOOP_SUM = """\
def total(nums):
    # add them up
    result = 0
    for n in nums:
        result += n
    return result
"""

# LOOP_SUM in another student's style: other names, a docstring, type hints, other spacing.
LOOP_SUM_DISGUISED = '''\
def total(values: list[int]) -> int:
    """Return the sum."""
    acc: int = 0
    for v in values:
        acc+=v
    return acc
'''

BUILTIN_SUM = """\
def total(nums):
    return sum(nums)
"""


def _sub(
    sid: int,
    student: str,
    code: str = LOOP_SUM,
    *,
    minutes: float = 0,
    stats: dict[str, Any] | None = None,
    status: str | None = "accepted",
    problem_id: str = "cs1.loops.total",
) -> SubmissionInfo:
    return SubmissionInfo(
        id=sid,
        student=student,
        problem_id=problem_id,
        function_name="total",
        created_at=START + timedelta(minutes=minutes),
        code=code,
        editor_stats=stats,
        result_status=status,
    )


def _stats(*, typed: int = 0, paste: int = 0, active_ms: int = 60_000) -> dict[str, Any]:
    return {
        "since_open_ms": active_ms + 10_000,
        "active_ms": active_ms,
        "typed_chars": typed,
        "pasted_chars": paste,
        "paste_count": 1 if paste else 0,
        "largest_paste_chars": paste,
        "edit_count": typed + (1 if paste else 0),
        "restored_draft": False,
    }


def _kinds(flags: list[Any], sid: int) -> set[FlagKind]:
    return {flag.kind for flag in flags if flag.submission_id == sid}


# --- normalize: the rename-proof form ---


def test_names_layout_comments_docstrings_and_hints_do_not_matter() -> None:
    assert canonical(LOOP_SUM, "total") == canonical(LOOP_SUM_DISGUISED, "total")
    assert canonical(LOOP_SUM, "total") == (
        "def total(v0):\n    v1 = 0\n    for v2 in v0:\n        v1 += v2\n    return v1"
    )


def test_the_sim_disguises_of_every_solution_have_the_same_form() -> None:
    rng = random.Random(0)
    for problem in load_all():
        disguised = reformat(rename_identifiers(problem.solution_code, problem.function_name, rng))
        assert canonical(disguised, problem.function_name) == canonical(
            problem.solution_code, problem.function_name
        ), problem.id


def test_a_different_program_is_not_the_same_structure() -> None:
    loop = fingerprints(canonical(LOOP_SUM, "total") or "")
    builtin = fingerprints(canonical(BUILTIN_SUM, "total") or "")
    assert similarity(loop, builtin) < 0.5
    assert similarity(loop, loop) == 1.0


def test_a_one_character_bug_is_close_but_not_the_same() -> None:
    buggy = LOOP_SUM.replace("result = 0", "result = 1")
    score = similarity(
        fingerprints(canonical(LOOP_SUM, "total") or ""),
        fingerprints(canonical(buggy, "total") or ""),
    )
    assert 0.5 < score < 1.0


def test_helper_names_are_renamed_but_builtins_and_imports_are_kept() -> None:
    a = "import math\ndef total(n):\n    return helper(n)\n"
    a += "def helper(x):\n    return math.sqrt(len(x))\n"
    b = "import math\ndef total(m):\n    return aux(m)\n"
    b += "def aux(y):\n    return math.sqrt(len(y))\n"
    assert canonical(a, "total") == canonical(b, "total")
    assert "math.sqrt(len(" in (canonical(a, "total") or "")


@pytest.mark.parametrize("code", ["def total(:\n", "x = 1\x00\n"])
def test_code_that_does_not_parse_has_no_form(code: str) -> None:
    assert canonical(code, "total") is None


def test_a_tiny_program_still_has_one_fingerprint() -> None:
    assert fingerprints("x") == frozenset({("x", "NEWLINE")})


# --- entry signals: paste and fast typing ---


@pytest.mark.parametrize(("pasted", "fires"), [(len(LOOP_SUM) // 2, True), (40, False)])
def test_paste_fires_at_its_threshold(pasted: int, fires: bool) -> None:
    config = IntegrityConfig(paste_share=(len(LOOP_SUM) // 2) / len(LOOP_SUM))
    flags = detect([_sub(1, "ana", stats=_stats(paste=pasted))], {}, config)
    assert (FlagKind.PASTE in _kinds(flags, 1)) is fires


def test_fast_typing_needs_speed_and_most_of_the_code_typed() -> None:
    n = len(LOOP_SUM)
    fast = _stats(typed=n, active_ms=n * 100)  # 10 characters per second
    slow = _stats(typed=n, active_ms=n * 400)  # 2.5 per second
    little = _stats(typed=n // 2, active_ms=n * 50)  # fast, but only half the code typed
    flags = detect(
        [
            _sub(1, "ana", stats=fast),
            _sub(2, "ben", stats=slow, problem_id="cs1.loops.b"),
            _sub(3, "cem", stats=little, problem_id="cs1.loops.c"),
        ],
        {},
    )
    assert [(f.submission_id, f.kind) for f in flags] == [(1, FlagKind.FAST_TYPING)]
    assert flags[0].value == pytest.approx(10.0)


def test_a_big_paste_is_a_paste_not_fast_typing() -> None:
    stats = _stats(typed=len(LOOP_SUM), paste=len(LOOP_SUM), active_ms=1_000)
    assert _kinds(detect([_sub(1, "ana", stats=stats)], {}), 1) == {FlagKind.PASTE}


def test_no_editor_data_means_no_entry_signal() -> None:
    assert detect([_sub(1, "ana", stats=None)], {}) == []


def test_the_paste_habit_is_context_in_the_reason_and_changes_no_flag() -> None:
    big = _stats(paste=len(LOOP_SUM))
    subs = [
        _sub(1, "ana", stats=big, status="wrong_answer", problem_id="cs1.loops.a"),
        _sub(2, "ana", stats=big, problem_id="cs1.loops.b"),
        _sub(3, "ana", stats=_stats(typed=200), problem_id="cs1.loops.c"),
    ]
    paste_flags = [f for f in detect(subs, {}) if f.kind == FlagKind.PASTE]
    assert [f.submission_id for f in paste_flags] == [1, 2]
    assert "2 of 3 submissions (1 of those not accepted)" in paste_flags[0].reason
    assert paste_flags[0].details["student_pasted"] == 2


# --- content signals: the same structure as another student or a known AI answer ---


def test_only_the_later_submission_of_another_student_is_flagged() -> None:
    subs = [
        _sub(1, "ana", minutes=0),
        _sub(2, "ana", LOOP_SUM_DISGUISED, minutes=5),  # her own code again: not a copy
        _sub(3, "ben", LOOP_SUM_DISGUISED, minutes=60),
    ]
    flags = detect(subs, {})
    assert [(f.submission_id, f.kind) for f in flags] == [(3, FlagKind.SAME_AS_STUDENT)]
    assert flags[0].details == {
        "matched_submission_id": 1,  # the earliest of the equal matches
        "matched_student": "ana",
        "gap_s": 3600.0,
        "students_matching": 1,
    }
    assert "ana's submission #1, 1 h earlier" in flags[0].reason


def test_the_same_time_is_not_earlier() -> None:
    assert detect([_sub(1, "ana"), _sub(2, "ben")], {}) == []


def test_different_code_or_another_problem_is_not_a_match() -> None:
    subs = [
        _sub(1, "ana"),
        _sub(2, "ben", BUILTIN_SUM, minutes=10),
        _sub(3, "cem", minutes=20, problem_id="cs1.loops.other"),
    ]
    assert detect(subs, {}) == []


def test_a_known_ai_answer_is_found_through_a_disguise() -> None:
    known = {"cs1.loops.total": [KnownAnswer("ollama/model#seed2", LOOP_SUM)]}
    flags = detect([_sub(1, "ana", LOOP_SUM_DISGUISED)], known)
    assert [(f.kind, f.value, f.details["ai_ref"]) for f in flags] == [
        (FlagKind.SAME_AS_AI, 1.0, "ollama/model#seed2")
    ]


def test_code_that_does_not_parse_gets_no_content_signal() -> None:
    known = {"cs1.loops.total": [KnownAnswer("m#seed0", "def total(:\n")]}
    subs = [_sub(1, "ana", "def total(:\n"), _sub(2, "ben", "def total(:\n", minutes=9)]
    assert detect(subs, known) == []


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        ({FlagKind.PASTE, FlagKind.SAME_AS_STUDENT}, True),
        ({FlagKind.FAST_TYPING, FlagKind.SAME_AS_AI}, True),
        ({FlagKind.PASTE, FlagKind.FAST_TYPING}, False),
        ({FlagKind.SAME_AS_STUDENT, FlagKind.SAME_AS_AI}, False),
        (set(), False),
    ],
)
def test_needs_review_wants_an_entry_and_a_content_signal(
    kinds: set[FlagKind], expected: bool
) -> None:
    assert needs_review(kinds) is expected


def test_detect_does_not_depend_on_the_input_order() -> None:
    subs = [
        _sub(1, "ana", stats=_stats(paste=len(LOOP_SUM))),
        _sub(2, "ben", LOOP_SUM_DISGUISED, minutes=3, stats=_stats(paste=len(LOOP_SUM))),
        _sub(3, "cem", LOOP_SUM, minutes=7, stats=_stats(typed=500, active_ms=10_000)),
    ]
    known = {"cs1.loops.total": [KnownAnswer("m#seed0", BUILTIN_SUM)]}
    assert detect(subs, known) == detect(list(reversed(subs)), known)


def test_the_checks_never_import_the_simulation() -> None:
    # The labels live in codetutor.sim; the detectors must work from the database's view only.
    # (known_ai.py may: it reads the reference seeds, not labels.)
    for name in ("normalize.py", "signals.py", "store.py"):
        tree = ast.parse((SRC / "integrity" / name).read_text(encoding="utf-8"))
        imported = [
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert imported and not [m for m in imported if (m or "").startswith("codetutor.sim")]


def test_the_known_ai_answers_are_the_reference_seeds_only() -> None:
    problems = load_all()
    known = known_ai_answers(problems)
    reference = CohortConfig().reference_seeds
    refs = [answer.ref for answers in known.values() for answer in answers]
    assert all(answers for answers in known.values())  # every problem has some
    assert {ref.rsplit("#seed", 1)[1] for ref in refs} == {str(seed) for seed in reference}


def test_the_config_is_frozen_and_rejects_typos() -> None:
    with pytest.raises(ValueError, match="paste_shre"):
        IntegrityConfig(paste_shre=0.4)  # type: ignore[call-arg]


# --- the database side ---


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    """A bank with one real problem (fast to sync)."""
    name = "celsius_to_fahrenheit"
    shutil.copytree(
        REPO / "problems" / "cs1" / "01_variables" / name, tmp_path / "cs1" / "01_variables" / name
    )
    return tmp_path


@pytest.fixture
def two_copies(db_session: Session, bank: Path) -> Callable[[], list[int]]:
    """Ana submits, then Ben pastes the same structure an hour later."""

    def make() -> list[int]:
        sync_problems(db_session, bank)
        code = "def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32\n"
        disguised = "def celsius_to_fahrenheit(temp):\n    return temp*9/5 + 32\n"
        ids = []
        for name, text, minutes, stats in [
            ("ana", code, 0, _stats(typed=120)),
            ("ben", disguised, 60, _stats(paste=len(disguised))),
        ]:
            user = get_or_create_user(db_session, name)
            ids.append(
                enqueue_submission(
                    db_session,
                    user,
                    "cs1.variables.celsius_to_fahrenheit",
                    text,
                    editor_stats=stats,
                    created_at=START + timedelta(minutes=minutes),
                )
            )
        db_session.commit()
        return ids

    return make


def test_the_batch_job_stores_flags_and_a_rerun_replaces_them(
    db_session: Session, two_copies: Callable[[], list[int]]
) -> None:
    ana, ben = two_copies()
    submissions = load_submissions(db_session)
    assert [(s.id, s.student, s.function_name) for s in submissions] == [
        (ana, "ana", "celsius_to_fahrenheit"),
        (ben, "ben", "celsius_to_fahrenheit"),
    ]
    flags = detect(submissions, {})
    for _ in range(2):
        replace_flags(db_session, flags)
        db_session.commit()
    stored = db_session.scalars(select(IntegrityFlagRow).order_by(IntegrityFlagRow.kind)).all()
    assert [(row.submission_id, row.kind) for row in stored] == [
        (ben, "paste"),
        (ben, "same_as_student"),
    ]
    assert {row.detector_version for row in stored} == {INTEGRITY_VERSION}
    assert stored[1].details["matched_submission_id"] == ana


@pytest.mark.parametrize("kind", list(FlagKind))
def test_every_flag_kind_is_allowed(
    db_session: Session, two_copies: Callable[[], list[int]], kind: FlagKind
) -> None:
    sid = two_copies()[0]
    db_session.add(_row(sid, kind=kind.value))
    db_session.flush()


@pytest.mark.parametrize(
    "columns", [{"kind": "looks_suspicious"}, {"details": ["not", "an", "object"]}]
)
def test_the_flags_table_refuses_bad_rows(
    db_session: Session, two_copies: Callable[[], list[int]], columns: dict[str, Any]
) -> None:
    sid = two_copies()[0]
    db_session.add(_row(sid, **columns))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_one_row_per_signal_and_submission(
    db_session: Session, two_copies: Callable[[], list[int]]
) -> None:
    sid = two_copies()[0]
    db_session.add_all([_row(sid), _row(sid)])
    with pytest.raises(IntegrityError):
        db_session.flush()


def _row(submission_id: int, **columns: Any) -> IntegrityFlagRow:
    values: dict[str, Any] = {
        "submission_id": submission_id,
        "kind": "paste",
        "value": 1.0,
        "reason": "One paste.",
        "details": {},
        "detector_version": INTEGRITY_VERSION,
    } | columns
    return IntegrityFlagRow(**values)


def test_no_api_code_reads_the_flags() -> None:
    # Students must never see flags; the Week 8 teacher screens will need their own route.
    for path in sorted((SRC / "api").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert "integrity_flags" not in source and "IntegrityFlagRow" not in source, path


def test_submission_rows_are_untouched_by_the_checks(
    db_session: Session, two_copies: Callable[[], list[int]]
) -> None:
    two_copies()
    before = [(s.id, s.code, s.job_status) for s in db_session.scalars(select(SubmissionRow))]
    replace_flags(db_session, detect(load_submissions(db_session), {}))
    db_session.commit()
    after = [(s.id, s.code, s.job_status) for s in db_session.scalars(select(SubmissionRow))]
    assert after == before
