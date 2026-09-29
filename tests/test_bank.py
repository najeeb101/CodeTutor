"""Tests for the problem-bank tools: fill_expected, the validator and the dataset build."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from codetutor.bank.build import FULL_FILE, STUDENT_FILE, build_dataset, content_hash
from codetutor.bank.expected import check_expected, fill_expected, write_tests_yaml
from codetutor.bank.validate import validate_problem
from codetutor.problems import Problem, load_problem
from conftest import SOLUTION, ProblemWriter, valid_problem_data, valid_tests


def _problem(**changes: Any) -> Problem:
    return Problem.model_validate({**valid_problem_data(), **changes})


def _inputs_only() -> list[dict[str, Any]]:
    tests = valid_tests()
    for test in tests:
        del test["expected"]
    return tests


# --- Writing tests.yaml ---


def test_yaml_writer_round_trips_tricky_values(tmp_path: Path) -> None:
    tricky: list[Any] = [
        1e16,  # PyYAML reads "1e+16" as a string; the writer must write 1.0e+16
        -0.0,
        "no",  # YAML 1.1 would read a bare `no` as False
        None,
        True,
        "مرحبا ✓",  # unicode (Arabic text + a symbol)
        [1, [2.5, "x"], {"k": None}],
        {"a b": [], "": {}},
    ]
    problem = _problem()  # 8 tests, one tricky value each
    expected = {test.id: value for test, value in zip(problem.tests, tricky, strict=True)}

    write_tests_yaml(tmp_path, problem, expected)

    written = yaml.safe_load((tmp_path / "tests.yaml").read_text(encoding="utf-8"))["tests"]
    for entry in written:
        value = expected[entry["id"]]
        assert json.dumps(entry["expected"]) == json.dumps(value), entry["id"]


def test_fill_expected_fills_missing_values_then_changes_nothing(
    write_problem: ProblemWriter,
) -> None:
    folder = write_problem(tests=_inputs_only())

    problem, changed = fill_expected(folder)
    assert changed == len(problem.tests)
    assert [test.expected for test in problem.tests] == [t["expected"] for t in valid_tests()]

    _, changed_again = fill_expected(folder)
    assert changed_again == 0


def test_fill_expected_keeps_order_ids_and_notes(write_problem: ProblemWriter) -> None:
    tests = _inputs_only()
    tests[0]["note"] = "example 1"
    folder = write_problem(tests=tests)

    problem, _ = fill_expected(folder)

    assert [test.id for test in problem.tests] == [t["id"] for t in tests]
    assert problem.tests[0].note == "example 1"


def test_check_expected_reports_a_wrong_stored_value() -> None:
    tests = valid_tests()
    tests[0]["expected"] = 31  # the solution returns 30
    messages = check_expected(_problem(tests=tests))
    assert len(messages) == 1
    assert messages[0].startswith("t01:")


def test_check_expected_treats_int_and_float_as_different() -> None:
    tests = valid_tests()
    tests[0]["expected"] = 30.0  # the solution returns the int 30
    assert len(check_expected(_problem(tests=tests))) == 1


# --- Validator ---


def test_valid_problem_passes_validation() -> None:
    report = validate_problem(_problem())
    assert report.valid, report.errors
    assert (report.buggy_caught, report.buggy_total) == (1, 1)


def test_validator_catches_a_buggy_solution_that_passes_everything() -> None:
    report = validate_problem(_problem(buggy={"not_really_buggy": SOLUTION}))
    assert not report.valid
    assert any("buggy/not_really_buggy.py passed all tests" in e for e in report.errors)


def test_validator_catches_a_starter_that_passes_everything() -> None:
    report = validate_problem(_problem(starter_code=SOLUTION))
    assert any("starter.py passes all tests" in e for e in report.errors)


def test_validator_catches_a_wrong_solution() -> None:
    wrong = "def sum_of_evens(n):\n    return 0\n"
    report = validate_problem(_problem(solution_code=wrong))
    assert any("solution.py" in e for e in report.errors)


def test_validator_catches_a_wrong_expected_value() -> None:
    tests = valid_tests()
    tests[2]["expected"] = 3
    report = validate_problem(_problem(tests=tests))
    assert any(e.startswith("tests.yaml t03:") for e in report.errors)


def test_validator_records_bugs_that_only_hidden_tests_catch() -> None:
    # Wrong only for n <= 0, and every visible input is positive.
    crashes_on_zero = "def sum_of_evens(n):\n    return sum(range(2, n + 1, 2)) // (n // abs(n))\n"
    report = validate_problem(_problem(buggy={"crashes_on_zero": crashes_on_zero}))
    assert report.hidden_only_bugs == ["crashes_on_zero"]


def test_validator_requires_buggy_solutions() -> None:
    report = validate_problem(_problem(buggy={}))
    assert any("no buggy solutions" in e for e in report.errors)


# --- Dataset build (these fail until TODO(najeeb) content_hash is written) ---


def test_content_hash_is_stable_and_ignores_junk_files(write_problem: ProblemWriter) -> None:
    folder = write_problem()
    first = content_hash(folder)
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "junk.pyc").write_bytes(b"junk")
    (folder / "notes.txt").write_text("not part of the problem", encoding="utf-8")

    assert content_hash(folder) == first
    assert len(first) == 64  # sha256 as hex


def test_content_hash_changes_when_a_file_changes(write_problem: ProblemWriter) -> None:
    folder = write_problem()
    before = content_hash(folder)
    buggy = folder / "buggy" / "off_by_one.py"
    buggy.write_text(buggy.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert content_hash(folder) != before


def test_content_hash_changes_when_a_buggy_file_is_renamed(write_problem: ProblemWriter) -> None:
    folder = write_problem()
    before = content_hash(folder)
    (folder / "buggy" / "off_by_one.py").rename(folder / "buggy" / "wrong_range.py")
    assert content_hash(folder) != before


def test_build_writes_full_and_student_views(write_problem: ProblemWriter, tmp_path: Path) -> None:
    folder = write_problem()
    build_dataset(tmp_path / "problems", tmp_path / "dist")

    full_lines = (tmp_path / "dist" / FULL_FILE).read_text(encoding="utf-8").splitlines()
    student_lines = (tmp_path / "dist" / STUDENT_FILE).read_text(encoding="utf-8").splitlines()
    assert len(full_lines) == len(student_lines) == 1
    full, student = json.loads(full_lines[0]), json.loads(student_lines[0])

    assert full["content_hash"] == student["content_hash"] == content_hash(folder)
    assert full["solution_code"] == load_problem(folder).solution_code
    for secret in ("solution_code", "buggy", "hints", "tests"):
        assert secret not in student
    assert [example["id"] for example in student["examples"]] == ["t01", "t02", "t03", "t04"]


def test_build_is_deterministic(write_problem: ProblemWriter, tmp_path: Path) -> None:
    write_problem()
    paths = build_dataset(tmp_path / "problems", tmp_path / "dist")
    first = [path.read_bytes() for path in paths]
    build_dataset(tmp_path / "problems", tmp_path / "dist")
    assert [path.read_bytes() for path in paths] == first
