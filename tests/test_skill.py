"""Difficulty and skill estimates (Week 5 Step 3): the Rasch fit, first attempts, scoring and
the report. Small hand-made classes, no database. See docs/integrity.md §3."""

from __future__ import annotations

import ast
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codetutor.integrity.signals import SubmissionInfo
from codetutor.skill.evaluate import (
    bootstrap_pearson,
    compare,
    declared_vs_estimated,
    drop_random,
    pearson,
    ranks,
)
from codetutor.skill.load import first_attempts
from codetutor.skill.rasch import (
    Response,
    fit_rasch,
    logit_difficulty,
    pass_rate_baselines,
    sigmoid,
)
from codetutor.skill.report import ClassData, render_report

SRC = Path(__file__).resolve().parents[1] / "src" / "codetutor"
START = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
TRUE_SKILL = {"ana": -1.5, "ben": -0.5, "cem": 0.5, "dan": 1.5}
TRUE_DIFFICULTY = {"p1": -1.0, "p2": 0.0, "p3": 1.0}


def _class(extra_students: int = 0) -> list[Response]:
    """Each student solves a problem when the true chance is at least 0.5, with some noise
    smoothed out by repeating the pattern for `extra_students` more copies of each student."""
    responses = []
    for copy in range(1 + extra_students):
        for s, theta in TRUE_SKILL.items():
            for p, b in TRUE_DIFFICULTY.items():
                solved = sigmoid(theta - b + (0.3 if copy % 2 else -0.3)) >= 0.5
                responses.append(Response(f"{s}{copy}", p, solved))
    return responses


def test_rasch_orders_students_and_problems_like_the_truth() -> None:
    fit = fit_rasch(_class(extra_students=3))
    by_skill = sorted(TRUE_SKILL, key=lambda s: fit.skill[f"{s}0"])
    assert by_skill == sorted(TRUE_SKILL, key=TRUE_SKILL.get)
    assert sorted(fit.difficulty, key=fit.difficulty.get) == ["p1", "p2", "p3"]
    assert fit.converged


def test_perfect_and_zero_scores_stay_finite_thanks_to_the_prior() -> None:
    responses = [Response("all", p, True) for p in "abc"] + [
        Response("none", p, False) for p in "abc"
    ]
    responses += [
        Response("mid", "a", True),
        Response("mid", "b", False),
        Response("mid", "c", True),
    ]
    fit = fit_rasch(responses)
    assert all(abs(v) < 5 for v in fit.skill.values())
    assert fit.skill["none"] < fit.skill["mid"] < fit.skill["all"]


def test_difficulty_is_centred_and_the_fit_is_deterministic_and_order_free() -> None:
    responses = _class(extra_students=2)
    fit = fit_rasch(responses)
    assert sum(fit.difficulty.values()) == pytest.approx(0.0, abs=1e-9)
    assert fit_rasch(list(reversed(responses))).difficulty == fit.difficulty
    assert fit_rasch(responses) == fit


def test_one_extra_perfect_student_barely_moves_the_difficulties() -> None:
    base = _class(extra_students=3)
    plus = [*base, *(Response("ace", p, True) for p in TRUE_DIFFICULTY)]
    before, after = fit_rasch(base).difficulty, fit_rasch(plus).difficulty
    assert max(abs(before[p] - after[p]) for p in before) < 0.2


def test_the_pass_rate_baseline_is_monotone_and_finite_at_the_edges() -> None:
    values = [logit_difficulty(solved, 10) for solved in range(11)]
    assert values == sorted(values, reverse=True)  # more solves = easier = lower
    assert all(abs(v) < 5 for v in values)
    skill, difficulty = pass_rate_baselines(_class())
    assert skill["dan0"] > skill["ana0"] and difficulty["p3"] > difficulty["p1"]


def _sub(
    sid: int, student: str, minutes: int, status: str | None, problem: str = "p1"
) -> SubmissionInfo:
    return SubmissionInfo(
        id=sid,
        student=student,
        problem_id="p1",
        function_name="f",
        created_at=START + timedelta(minutes=minutes),
        code="",
        editor_stats=None,
        result_status=status,
    )


def test_first_attempts_take_the_earliest_row_and_skip_ungraded() -> None:
    subs = [
        _sub(3, "ana", 20, "accepted"),  # a later retry: ignored
        _sub(1, "ana", 0, "wrong_answer"),
        _sub(2, "ben", 5, None),  # first try not graded yet
        _sub(4, "cem", 7, "accepted"),
        _sub(5, "cem", 7, "wrong_answer"),  # same time: the lower id is first
    ]
    result = first_attempts(subs)
    assert [(r.student, r.solved) for r in result.responses] == [("ana", False), ("cem", True)]
    assert result.ungraded == 1


def test_excluded_first_tries_are_left_out_not_replaced_by_the_second() -> None:
    subs = [
        _sub(1, "ana", 0, "accepted"),
        _sub(2, "ana", 9, "wrong_answer"),
        _sub(3, "ben", 1, "accepted"),
    ]
    result = first_attempts(subs, exclude={1})
    assert [r.student for r in result.responses] == ["ben"]
    assert result.excluded == 1


def test_scoring_helpers() -> None:
    assert pearson([1, 2, 3], [2, 4, 6]) == pytest.approx(1.0)
    assert pearson([1, 1, 1], [1, 2, 3]) == 0.0
    assert ranks([10, 20, 20, 5]) == [2.0, 3.5, 3.5, 1.0]
    shifted = compare({"a": 1.0, "b": 2.0, "c": 4.0}, {"a": 11.0, "b": 12.0, "c": 14.0})
    assert shifted.pearson == pytest.approx(1.0) and shifted.rmse == pytest.approx(0.0, abs=1e-12)
    assert shifted.n == 3


def test_the_bootstrap_resamples_units_and_is_deterministic() -> None:
    truth = {f"s{i}": float(i) for i in range(20)}
    estimate = {k: v + (3.0 if int(k[1:]) % 2 else -3.0) for k, v in truth.items()}
    low, high = bootstrap_pearson(estimate, truth, rounds=200)
    assert low < pearson(list(estimate.values()), list(truth.values())) < high
    assert (low, high) == bootstrap_pearson(estimate, truth, rounds=200)


def test_random_deletion_keeps_about_the_right_share_and_is_seeded() -> None:
    responses = _class(extra_students=40)
    kept = drop_random(responses, random.Random(0))
    assert 0.6 < len(kept) / len(responses) < 0.8
    assert kept == drop_random(responses, random.Random(0))


def test_declared_levels_are_compared_with_their_own_average() -> None:
    checks = declared_vs_estimated(
        {"a": -1.0, "b": -0.2, "c": 1.0}, {"a": "easy", "b": "easy", "c": "hard"}
    )
    assert {c.problem: round(c.gap, 2) for c in checks} == {"a": -0.4, "b": 0.4, "c": 0.0}


def _data(seed: int) -> ClassData:
    responses = _class(extra_students=5)
    return ClassData(
        seed=seed,
        database=f"codetutor_sim_s{seed}",
        cohort_file=f"lab/sim/cohort-s{seed}.jsonl",
        cohort_sha256="0" * 64,
        submissions=len(responses) + 3,
        responses=responses,
        clean=responses[:-2],
        ungraded=0,
        excluded=2,
        true_skill={r.student: TRUE_SKILL[r.student[:-1]] for r in responses},
        true_difficulty=TRUE_DIFFICULTY,
        declared={"p1": "easy", "p2": "medium", "p3": "hard"},
    )


def test_the_report_is_byte_identical_and_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("codetutor.skill.report.ROUNDS", 50)  # the full 2000 are for the real run
    monkeypatch.setattr("codetutor.skill.evaluate.REPEATS", 2)
    first = render_report([_data(0), _data(1)])
    assert first == render_report([_data(0), _data(1)])
    for part in ("## 1.", "## 2.", "## 3.", "## 4.", "## 5.", "seed 0", "seed 1", "Rasch"):
        assert part in first
    assert "None" not in first and "nan" not in first.lower()


def test_the_estimators_never_import_the_simulation() -> None:
    for name in ("rasch.py", "load.py"):
        tree = ast.parse((SRC / "skill" / name).read_text(encoding="utf-8"))
        imported = [
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        ]
        assert imported and not [m for m in imported if (m or "").startswith("codetutor.sim")]
