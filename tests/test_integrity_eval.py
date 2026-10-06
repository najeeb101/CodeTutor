"""Scoring the integrity checks (Week 5 Step 2c): F0.5, the fast threshold search, intervals
over students and the report. Small hand-made classes, no database. See docs/integrity.md §2.4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from codetutor.integrity.evaluate import (
    FastFlags,
    GridPoint,
    Labelled,
    LabelMismatchError,
    Scores,
    _rank,
    f_beta,
    grid_configs,
    labelled,
    review_ids,
    score,
    search,
    student_intervals,
    student_view,
)
from codetutor.integrity.report import ClassData, ThresholdsNotFrozenError, render_report
from codetutor.integrity.signals import (
    IntegrityConfig,
    KnownAnswer,
    SubmissionInfo,
    detect,
)
from codetutor.sim.cohort import CohortRow, Entry, Label, Transform
from codetutor.sim.personas import Persona
from codetutor.sim.pools import SourceKind

START = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
PROBLEM = "cs1.loops.total"

# Long enough that small edits keep the structure similar: SIMILAR_90 scores 0.905 against
# BASE and SIMILAR_88 0.884 (measured), so the similarity thresholds 0.8 / 0.9 / 1.0 differ.
BASE = """\
def total(nums):
    positives = 0
    negatives = 0
    zeros = 0
    for n in nums:
        if n > 0:
            positives += n
        elif n < 0:
            negatives += n
        else:
            zeros += 1
    result = positives + negatives
    if zeros > 3:
        result = result * 2
    return result
"""
SIMILAR_90 = BASE.replace("result * 2", "result * 3")
SIMILAR_88 = BASE.replace("zeros += 1", "zeros = zeros + 1")
OTHER = "def total(nums):\n    return sum(nums)\n"


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


def _typed(code: str, chars_per_s: float) -> dict[str, Any]:
    return _stats(typed=len(code), active_ms=round(len(code) / chars_per_s * 1000))


def _pasted(code: str, share: float) -> dict[str, Any]:
    return _stats(typed=len(code) - round(share * len(code)), paste=round(share * len(code)))


def _sub(
    sid: int, student: str, code: str, stats: dict[str, Any] | None, minutes: float
) -> SubmissionInfo:
    return SubmissionInfo(
        id=sid,
        student=student,
        problem_id=PROBLEM,
        function_name="total",
        created_at=START + timedelta(minutes=minutes),
        code=code,
        editor_stats=stats,
        result_status="accepted",
    )


def _label(cheating: bool) -> Label:
    return Label(
        persona=Persona.COPIER if cheating else Persona.AVERAGE,
        source_kind=SourceKind.COPY if cheating else SourceKind.SOLUTION,
        source_ref="x",
        transform=Transform.NONE,
        intended_pass=True,
        cheating=cheating,
        entry=Entry.PASTED if cheating else Entry.TYPED,
    )


def _class(*subs: tuple[SubmissionInfo, bool]) -> list[Labelled]:
    return [Labelled(submission, _label(cheating)) for submission, cheating in subs]


def _row(submission: SubmissionInfo, cheating: bool) -> CohortRow:
    return CohortRow(
        key=f"{submission.student}/{submission.problem_id}/1",
        student=submission.student,
        problem_id=submission.problem_id,
        problem_version=1,
        attempt=1,
        created_at=submission.created_at,
        code=submission.code,
        editor_stats=dict(submission.editor_stats or {}),
        label=_label(cheating),
    )


# A class whose search picks the frozen defaults (paste 0.9 / 5 chars/s / similarity 1.0):
# every paste is a whole program and every copy exact (so those thresholds tie and the
# strictest wins), and one retyper types 5.5 characters per second (caught at 3-5, missed at
# 6-7: speed 5 is the strictest setting that catches everyone).
FROZEN_CLASS = _class(
    (_sub(1, "ana", BASE, _typed(BASE, 1.0), 0), False),
    (_sub(2, "ben", BASE, _pasted(BASE, 1.0), 10), True),
    (_sub(3, "cem", BASE, _typed(BASE, 5.5), 20), True),
    (_sub(4, "dan", OTHER, _typed(OTHER, 1.0), 30), False),
)


# --- F-beta and scores ---


def test_f_beta_known_values() -> None:
    assert f_beta(1.0, 1.0) == 1.0
    assert f_beta(0.5, 1.0, beta=1.0) == pytest.approx(2 / 3)  # F1: the harmonic mean
    assert f_beta(0.5, 1.0) == pytest.approx(1.25 * 0.5 / (0.25 * 0.5 + 1.0))
    assert f_beta(0.0, 0.0) == 0.0
    assert f_beta(0.0, 1.0) == 0.0


def test_f_half_prefers_precision() -> None:
    assert f_beta(0.9, 0.5) > f_beta(0.5, 0.9)
    assert f_beta(0.9, 0.5, beta=1.0) == pytest.approx(f_beta(0.5, 0.9, beta=1.0))


def test_scores_count_only_flags_of_this_class() -> None:
    scores = score({2, 4, 99}, FROZEN_CLASS)  # 99 is not in the class
    assert (scores.flagged, scores.true_positives, scores.positives) == (2, 1, 2)
    assert (scores.precision, scores.recall) == (0.5, 0.5)
    assert Scores(0, 0, 2).precision is None


def test_labels_join_by_student_problem_and_time() -> None:
    submissions = [row.submission for row in FROZEN_CLASS]
    rows = [_row(row.submission, row.label.cheating) for row in FROZEN_CLASS]
    joined = labelled(list(reversed(submissions)), rows)
    assert [(j.submission.id, j.label.cheating) for j in joined] == [
        (4, False),
        (3, True),
        (2, True),
        (1, False),
    ]
    with pytest.raises(LabelMismatchError):
        labelled(submissions[:3], rows)
    moved = [*rows[:3], rows[3].model_copy(update={"created_at": START})]
    with pytest.raises(LabelMismatchError):
        labelled(submissions, moved)


# --- the threshold search ---


def test_the_fast_search_gives_exactly_the_flags_of_detect_at_every_grid_point() -> None:
    subs = [
        _sub(1, "ana", BASE, _typed(BASE, 1.0), 0),
        _sub(2, "ben", BASE, _pasted(BASE, 0.95), 10),
        _sub(3, "cem", SIMILAR_90, _pasted(SIMILAR_90, 0.6), 20),
        _sub(4, "dan", SIMILAR_88, _pasted(SIMILAR_88, 0.4), 30),
        _sub(5, "eva", BASE, _typed(BASE, 3.5), 40),
        _sub(6, "fay", SIMILAR_90, _typed(SIMILAR_90, 4.5), 50),
        _sub(7, "gil", SIMILAR_88, _typed(SIMILAR_88, 6.5), 60),
        _sub(8, "hal", OTHER, _pasted(OTHER, 0.8), 70),
    ]
    known = {PROBLEM: [KnownAnswer("m#seed0", SIMILAR_90)]}
    fast = FastFlags(subs, known)
    seen = set()
    for config in grid_configs():
        expected = [(f.submission_id, f.kind, f.value) for f in detect(subs, known, config)]
        assert [(f.submission_id, f.kind, f.value) for f in fast.flags(config)] == expected
        seen.add(tuple(expected))
    assert len(seen) > 10  # the class really moves with every threshold


def test_the_fast_search_refuses_a_similarity_below_its_precomputed_one() -> None:
    fast = FastFlags([], {})
    with pytest.raises(ValueError, match="below"):
        fast.flags(IntegrityConfig(similarity=0.5))


def test_best_f_first_then_fewer_flags_then_higher_thresholds() -> None:
    def point(paste: float, scores: Scores) -> GridPoint:
        return GridPoint(IntegrityConfig(paste_share=paste), scores)

    half = Scores(8, 4, 8)  # precision 0.5, recall 0.5
    half_fewer = Scores(4, 2, 4)  # the same F with fewer flags
    better = Scores(4, 3, 4)  # precision 0.75, recall 0.75
    ranked = sorted(
        [point(0.5, half), point(0.9, half), point(0.3, half_fewer), point(0.3, better)],
        key=_rank,
    )
    assert [(p.config.paste_share, p.scores.flagged) for p in ranked] == [
        (0.3, 4),  # best F
        (0.3, 4),  # same F as the next two, fewer flags
        (0.9, 8),  # same F and flags: the higher paste threshold
        (0.5, 8),
    ]
    assert ranked[0].scores is better


def test_the_search_on_a_class_picks_the_strictest_of_the_best() -> None:
    fast = FastFlags([row.submission for row in FROZEN_CLASS], {})
    points = search(fast, FROZEN_CLASS)
    assert len(points) == 60
    assert points[0].config == IntegrityConfig(paste_share=0.9, chars_per_s=5.0, similarity=1.0)
    assert points[0].scores.f == 1.0
    assert review_ids(fast.flags(points[0].config)) == {2, 3}


# --- intervals over students ---


def test_one_student_gives_a_zero_width_interval() -> None:
    rows = _class((_sub(1, "ana", BASE, None, 0), True), (_sub(2, "ana", OTHER, None, 5), False))
    precision, recall = student_intervals({1, 2}, rows, rounds=50)
    assert precision is not None and (precision.low, precision.high) == (0.5, 0.5)
    assert recall is not None and (recall.low, recall.high) == (1.0, 1.0)


def test_intervals_resample_students_not_rows() -> None:
    # ana's 5 flags are all right, ben's 5 all wrong: drawing students gives precision 0, 0.5
    # or 1, so the interval spans everything. Rows drawn one by one would stay near 0.5.
    rows = _class(
        *[(_sub(i, "ana", BASE, None, i), True) for i in range(5)],
        *[(_sub(10 + i, "ben", BASE, None, i), False) for i in range(5)],
    )
    precision, _ = student_intervals({*range(5), *range(10, 15)}, rows)
    assert precision is not None and (precision.low, precision.high) == (0.0, 1.0)
    assert student_intervals({1}, rows) == student_intervals({1}, rows)  # deterministic


def test_undefined_resamples_are_counted() -> None:
    rows = _class((_sub(1, "ana", BASE, None, 0), True), (_sub(2, "ben", BASE, None, 0), False))
    precision, recall = student_intervals({1}, rows, rounds=200)
    # Drawing ben twice flags nothing and has no cheating: no precision, no recall.
    assert precision is not None and precision.undefined > 0
    assert recall is not None and recall.undefined == precision.undefined


def test_the_student_view_counts_students() -> None:
    view = student_view({2, 4}, FROZEN_CLASS)
    assert (view.cheating_students, view.cheating_students_flagged) == (2, 1)
    assert (view.honest_students, view.honest_students_flagged) == (2, 1)


# --- the report ---


def _data(seed: int, rows: list[Labelled]) -> ClassData:
    return ClassData(
        seed=seed,
        database=f"codetutor_sim_s{seed}",
        cohort_file=f"lab/sim/cohort-s{seed}.jsonl",
        cohort_sha256="0" * 64,
        rows=rows,
        fast=FastFlags([row.submission for row in rows], {}),
    )


def test_the_report_is_byte_identical_and_names_the_chosen_setting() -> None:
    first = render_report(_data(0, FROZEN_CLASS), _data(1, FROZEN_CLASS))
    second = render_report(_data(0, FROZEN_CLASS), _data(1, FROZEN_CLASS))
    assert first == second
    assert "paste 0.9 / 5 chars/s / similarity 1.0" in first
    assert "| 1 | 0.9 | 5 | 1.0 | 2 | 1.00 | 1.00 | 1.000 ← chosen |" in first
    assert "None" not in first


def test_the_report_refuses_when_the_defaults_are_not_the_winner() -> None:
    # Without the 5.5 chars/s retyper, speed 7 is the strictest best: not the frozen 5.
    rows = [row for row in FROZEN_CLASS if row.submission.id != 3]
    with pytest.raises(ThresholdsNotFrozenError, match="7 chars/s"):
        render_report(_data(0, rows), _data(1, rows))
