"""Early warning (Week 8 Step 3a): features, labels, the model, the metrics, the report."""

from __future__ import annotations

import ast
import json
import math
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codetutor.early import evaluate, features, logistic, served
from codetutor.early.evaluate import auc, labels, precision_recall, top_k
from codetutor.early.features import FEATURE_NAMES, course_start, features_at, prefix, week_of
from codetutor.early.logistic import fit_logistic, model_from_json, model_to_json, predict
from codetutor.integrity.signals import SubmissionInfo

MONDAY = datetime(2026, 9, 7, tzinfo=UTC)


def sub(
    sid: int, student: str, problem: str, day: float, status: str | None = "accepted"
) -> SubmissionInfo:
    """One submission `day` days after the Monday that week 1 starts on."""
    return SubmissionInfo(
        id=sid,
        student=student,
        problem_id=problem,
        function_name="f",
        created_at=MONDAY + timedelta(days=day),
        code="def f(): pass",
        editor_stats=None,
        result_status=status,
    )


def small_class() -> list[SubmissionInfo]:
    """ann solves everything first try; bob fails everything he first tries after week 3."""
    rows = []
    sid = 0
    for student in ("ann", "bob"):
        for week in range(1, 7):
            for k in range(3):
                sid += 1
                bad = student == "bob" and week > 3
                rows.append(
                    sub(
                        sid,
                        student,
                        f"p{week}{k}",
                        (week - 1) * 7 + k,
                        "wrong_answer" if bad else "accepted",
                    )
                )
    return rows


# --- weeks -------------------------------------------------------------------


def test_course_start_is_the_monday_of_the_first_submission() -> None:
    rows = [sub(1, "a", "p", 2.5), sub(2, "a", "q", 9)]  # Wednesday and the next Wednesday
    assert course_start(rows) == MONDAY


def test_weeks_are_seven_day_buckets() -> None:
    assert week_of(MONDAY, MONDAY) == 1
    assert week_of(MONDAY + timedelta(days=6, hours=23), MONDAY) == 1
    assert week_of(MONDAY + timedelta(days=7), MONDAY) == 2


# --- features never see the future -------------------------------------------


def test_features_ignore_everything_after_the_cutoff() -> None:
    rows = small_class()
    before = features_at(rows, 3, MONDAY)
    # Change every later row completely: features at week 3 must not move.
    changed = [
        sub(r.id, r.student, r.problem_id, (r.created_at - MONDAY).days + 0.5, "timeout")
        if week_of(r.created_at, MONDAY) > 3
        else r
        for r in rows
    ]
    extra = [sub(9999, "ann", "late", 40, "accepted"), sub(9998, "zed", "late", 41)]
    assert features_at(changed + extra, 3, MONDAY) == before


def test_prefix_keeps_only_early_weeks() -> None:
    kept = prefix(small_class(), 2, MONDAY)
    assert kept and all(week_of(r.created_at, MONDAY) <= 2 for r in kept)


def test_feature_vector_has_one_number_per_name() -> None:
    vectors = features_at(small_class(), 3, MONDAY)
    assert set(vectors) == {"ann", "bob"}
    assert all(len(v) == len(FEATURE_NAMES) for v in vectors.values())
    first_try = FEATURE_NAMES.index("first_try_share")
    assert vectors["ann"][first_try] == 1.0


def test_students_with_no_submission_by_the_cutoff_have_no_features() -> None:
    rows = small_class() + [sub(5000, "late_joiner", "p", 30)]
    assert "late_joiner" not in features_at(rows, 3, MONDAY)


# --- labels -------------------------------------------------------------------


def test_label_is_the_later_first_try_share() -> None:
    found = labels(small_class(), 3, MONDAY)
    assert found == {"ann": False, "bob": True}


def test_label_uses_first_tries_only() -> None:
    rows = small_class()
    # bob solves one of his week-5 problems on a SECOND try: still a failed first try.
    rows.append(sub(7000, "bob", "p50", 4 * 7 + 5, "accepted"))
    assert labels(rows, 3, MONDAY)["bob"] is True


def test_students_without_a_graded_later_first_try_have_no_label() -> None:
    rows = [r for r in small_class() if week_of(r.created_at, MONDAY) <= 3]
    assert labels(rows, 3, MONDAY) == {}
    ungraded = rows + [sub(8000, "ann", "x", 30, None)]
    assert labels(ungraded, 3, MONDAY) == {}


# --- the model ----------------------------------------------------------------


def test_logistic_finds_the_direction_of_a_known_rule() -> None:
    rng = random.Random(1)
    rows, y = [], []
    for _ in range(300):
        a, b = rng.gauss(0, 1), rng.gauss(0, 1)
        rows.append([a, b, 5.0])  # third column is constant
        y.append(rng.random() < 1 / (1 + math.exp(-(2 * a - 1 * b))))
    model = fit_logistic(rows, y)
    assert model.weights[0] > 1.0 > 0 > model.weights[1]
    assert model.weights[2] == 0.0  # a constant column cannot get a weight
    assert predict(model, [3.0, -3.0, 5.0]) > 0.9 > 0.1 > predict(model, [-3.0, 3.0, 5.0])


def test_logistic_stays_finite_when_the_classes_separate_perfectly() -> None:
    rows = [[float(i)] for i in range(10)]
    y = [i >= 5 for i in range(10)]
    model = fit_logistic(rows, y)
    assert math.isfinite(model.weights[0]) and model.iterations < logistic.MAX_ITERATIONS


def test_logistic_refuses_empty_or_mismatched_input() -> None:
    with pytest.raises(ValueError, match="same, non-zero"):
        fit_logistic([], [])
    with pytest.raises(ValueError, match="same, non-zero"):
        fit_logistic([[1.0]], [True, False])


def test_solve_matches_a_hand_solution() -> None:
    assert logistic.solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0]) == pytest.approx([1.0, 3.0])


# --- the metrics ----------------------------------------------------------------


def test_auc_known_values() -> None:
    assert auc([0.9, 0.8, 0.2, 0.1], [True, True, False, False]) == 1.0
    assert auc([0.1, 0.2, 0.8, 0.9], [True, True, False, False]) == 0.0
    assert auc([0.5, 0.5], [True, False]) == 0.5  # a tie counts half
    assert auc([0.9, 0.3, 0.6, 0.1], [True, True, False, False]) == 0.75


def test_auc_needs_both_classes() -> None:
    with pytest.raises(ValueError, match="at least one"):
        auc([0.1, 0.2], [True, True])


def test_top_k_breaks_ties_by_name_and_precision_recall_follow() -> None:
    scores = {"b": 0.5, "a": 0.5, "c": 0.1}
    assert top_k(scores, {}, 2) == ["a", "b"]
    at_risk = {"a": True, "b": False, "c": True}
    assert precision_recall(["a", "b"], at_risk) == (0.5, 0.5)


# TODO(najeeb): write `test_auc_matches_the_rank_formula`. AUC can also be computed from ranks:
# with n_pos at-risk and n_neg other students, AUC = (sum of the ranks of the at-risk scores
# - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), where the lowest score has rank 1 and equal
# scores share the average rank. Hint: `codetutor.skill.evaluate.ranks` does the ranking.
# Compare it with `auc` on random scores that include ties (use `random.Random(seed)`).


# --- the experiment and the report --------------------------------------------------


def test_model_beats_chance_on_a_class_where_early_success_predicts_later_success() -> None:
    rng = random.Random(3)
    rows, sid = [], 0
    for n in range(40):
        ability = rng.random()
        for week in range(1, 7):
            for k in range(4):
                sid += 1
                ok = rng.random() < ability
                rows.append(
                    sub(
                        sid,
                        f"s{n:02d}",
                        f"p{week}{k}",
                        (week - 1) * 7 + k,
                        "accepted" if ok else "wrong_answer",
                    )
                )
    start = course_start(rows)
    model = evaluate.fit_for(rows, 3, start)
    result = evaluate.score_class(model, rows, 3, start)
    by_name = {m.name: m for m in result.methods}
    assert by_name["Logistic model"].auc > 0.7
    assert (
        by_name["Logistic model"].low
        < by_name["Logistic model"].auc
        < by_name["Logistic model"].high + 1e-9
    )
    assert len(result.flagged) == evaluate.TOP_K


def test_stoppers_are_students_missing_from_the_last_week() -> None:
    rows = small_class() + [sub(9000, "cat", "p", 1)]
    assert evaluate.stoppers(rows, MONDAY) == {"cat"}


def test_no_early_warning_code_reads_labels_or_the_database_tables() -> None:
    """The model sees submissions only: no cohort labels, no persona names, no tables."""
    forbidden = {"codetutor.sim", "codetutor.db.models"}
    for path in Path(features.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(node.module.startswith(f) for f in forbidden), path.name
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith(f) for a in node.names for f in forbidden)


# --- the model the API serves -----------------------------------------------------


def test_a_model_survives_a_round_trip_through_json() -> None:
    model = fit_logistic(
        [[0.0, 1.0], [1.0, 3.0], [2.0, 2.0], [3.0, 5.0]], [False, False, True, True]
    )
    again = model_from_json(json.loads(json.dumps(model_to_json(model))))
    assert again == model
    assert predict(again, [1.5, 2.5]) == predict(model, [1.5, 2.5])


def test_a_broken_saved_model_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="not a saved logistic model"):
        model_from_json({"means": [0.0]})
    with pytest.raises(ValueError, match="different lengths"):
        model_from_json(
            {"means": [0.0], "spreads": [1.0, 1.0], "weights": [0.0], "bias": 0, "iterations": 1}
        )


def test_the_committed_model_loads_and_scores_between_zero_and_one() -> None:
    loaded = served.load_served_model()
    assert loaded.cutoff == 3 and loaded.version == served.EARLY_VERSION
    for row in ([0.0, 0.0, 0.0, 0.0, 0.0, -5.0], [1.0, 40.0, 9.0, 30.0, 20.0, 5.0]):
        assert 0.0 <= predict(loaded.model, row) <= 1.0


def test_a_model_file_made_for_other_inputs_is_refused(tmp_path: Path) -> None:
    served.save_model(tmp_path / "m.json", served.load_served_model())
    data = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    data["feature_names"] = list(reversed(data["feature_names"]))
    (tmp_path / "m.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="export-model"):
        served.read_model(tmp_path / "m.json")


def test_risk_scores_wait_for_week_three_and_then_use_weeks_one_to_three_only() -> None:
    early = [r for r in small_class() if week_of(r.created_at, MONDAY) <= 2]
    assert served.risk_scores(early) is None
    assert served.risk_scores([]) is None
    rows = small_class()
    scores = served.risk_scores(rows)
    assert scores is not None and set(scores) == {"ann", "bob"}
    # Changing everything after week 3 does not move the score.
    later_changed = [
        sub(r.id, r.student, r.problem_id, (r.created_at - MONDAY).days, "timeout")
        if week_of(r.created_at, MONDAY) > 3
        else r
        for r in rows
    ]
    assert served.risk_scores(later_changed) == scores
