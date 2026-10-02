"""Tests for loading problem folders from disk."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from codetutor.problems import (
    DEFAULT_PROBLEMS_ROOT,
    ProblemLoadError,
    ProblemNotFoundError,
    get_problem,
    load_all,
    load_problem,
    parse_yaml,
)
from conftest import ProblemWriter, valid_meta, valid_tests

# --- one problem ---


def test_valid_folder_loads(write_problem: ProblemWriter) -> None:
    problem = load_problem(write_problem())
    assert problem.id == "cs1.loops.sum_of_evens"
    assert "def sum_of_evens" in problem.starter_code
    assert set(problem.buggy) == {"off_by_one"}


def test_problem_without_buggy_folder_loads(write_problem: ProblemWriter) -> None:
    problem = load_problem(write_problem(buggy={}))
    assert problem.buggy == {}


@pytest.mark.parametrize("missing", ["problem.yaml", "tests.yaml", "starter.py", "solution.py"])
def test_missing_file_names_the_file(write_problem: ProblemWriter, missing: str) -> None:
    folder = write_problem(skip=(missing,))
    with pytest.raises(ProblemLoadError, match=f"{missing}: file is missing"):
        load_problem(folder)


def test_broken_yaml_names_the_file(write_problem: ProblemWriter) -> None:
    folder = write_problem()
    (folder / "problem.yaml").write_text("id: [unclosed\n", encoding="utf-8")
    with pytest.raises(ProblemLoadError, match="problem.yaml: invalid YAML"):
        load_problem(folder)


def test_tests_yaml_needs_tests_key(write_problem: ProblemWriter) -> None:
    folder = write_problem()
    (folder / "tests.yaml").write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(ProblemLoadError, match="exactly one key, 'tests'"):
        load_problem(folder)


def test_schema_error_names_file_and_field(write_problem: ProblemWriter) -> None:
    tests = valid_tests()
    del tests[3]["hidden"]
    folder = write_problem(tests=tests)
    with pytest.raises(ProblemLoadError) as info:
        load_problem(folder)
    message = str(info.value)
    assert str(folder) in message
    assert "tests.yaml: tests[3].hidden: Field required" in message


def test_missing_expected_is_rejected_by_default(write_problem: ProblemWriter) -> None:
    tests = valid_tests()
    del tests[5]["expected"]
    folder = write_problem(tests=tests)
    with pytest.raises(ProblemLoadError, match="tests without 'expected': t06"):
        load_problem(folder)
    # fill_expected.py loads problems before expected values exist:
    problem = load_problem(folder, require_expected=False)
    assert not problem.tests[5].has_expected


def test_null_expected_counts_as_present(write_problem: ProblemWriter) -> None:
    tests = valid_tests()
    tests[0]["expected"] = None
    problem = load_problem(write_problem(tests=tests))
    assert problem.tests[0].has_expected


# --- the id must match the folder ---


def test_folder_matching_id_loads(write_problem: ProblemWriter) -> None:
    folder = write_problem(folder="cs1/03_loops/sum_of_evens")
    assert load_problem(folder).id == "cs1.loops.sum_of_evens"


@pytest.mark.parametrize(
    "folder",
    [
        "cs1/03_loops/sum_of_odds",  # problem slug differs
        "cs1/03_strings/sum_of_evens",  # module slug differs
        "cs1/04_loops/sum_of_evens",  # module number differs from module: 3
        "cs2/03_loops/sum_of_evens",  # course differs
        "cs1/loops/sum_of_evens",  # module folder has no "NN_" prefix
        "cs1/xx_loops/sum_of_evens",  # prefix is not a number
    ],
)
def test_folder_mismatch_is_rejected(write_problem: ProblemWriter, folder: str) -> None:
    path = write_problem(folder=folder)
    with pytest.raises(ProblemLoadError) as info:
        load_problem(path)
    assert str(path) in str(info.value)


# --- many problems ---


def _second_problem_meta() -> dict:
    meta = valid_meta()
    meta.update(id="cs1.variables.double_it", module=1, module_name="Variables", order=1)
    meta["function_name"] = "sum_of_evens"  # reuse the same starter/solution code
    return meta


def test_load_all_sorts_by_module_then_order(write_problem: ProblemWriter, tmp_path: Path) -> None:
    write_problem()  # module 3
    write_problem(meta=_second_problem_meta(), folder="cs1/01_variables/double_it")  # module 1
    problems = load_all(tmp_path / "problems")
    assert [p.id for p in problems] == ["cs1.variables.double_it", "cs1.loops.sum_of_evens"]


def test_load_all_rejects_duplicate_ids(write_problem: ProblemWriter, tmp_path: Path) -> None:
    write_problem()
    # Both folders give the id "cs1.loops.sum_of_evens" (module number isn't part of the id),
    # and each one passes the folder check on its own. Only the duplicate check catches it.
    meta = valid_meta()
    meta["module"] = 4
    write_problem(meta=meta, folder="cs1/04_loops/sum_of_evens")
    with pytest.raises(ProblemLoadError, match="duplicate problem id 'cs1.loops.sum_of_evens'"):
        load_all(tmp_path / "problems")


def test_load_all_rejects_duplicate_position(write_problem: ProblemWriter, tmp_path: Path) -> None:
    write_problem()
    meta = valid_meta()
    meta["id"] = "cs1.loops.other"
    write_problem(meta=meta, folder="cs1/03_loops/other")
    with pytest.raises(ProblemLoadError, match="module 3, order 1"):
        load_all(tmp_path / "problems")


def test_load_all_missing_root(tmp_path: Path) -> None:
    with pytest.raises(ProblemLoadError, match="not found"):
        load_all(tmp_path / "nope")


def test_get_problem(write_problem: ProblemWriter, tmp_path: Path) -> None:
    write_problem()
    root = tmp_path / "problems"
    assert get_problem("cs1.loops.sum_of_evens", root).title == "Sum of Even Numbers"
    with pytest.raises(ProblemNotFoundError, match="cs1.loops.nope"):
        get_problem("cs1.loops.nope", root)


# --- the real problem bank ---


def test_real_problem_bank_loads() -> None:
    # require_expected=False until fill_expected.py (Step 3) fills the expected values.
    problems = load_all(DEFAULT_PROBLEMS_ROOT, require_expected=False)
    assert "cs1.loops.sum_of_evens" in [p.id for p in problems]
    positions = [(p.module, p.order) for p in problems]
    assert positions == sorted(positions)
    for problem in problems:
        assert 1 <= len(problem.buggy) <= 3, f"{problem.id} needs 1-3 buggy solutions"


def test_fast_yaml_parser_reads_the_bank_like_the_reference_parser() -> None:
    # A differential test: libyaml (C) and PyYAML's pure-Python parser must read every bank
    # file the same, so machines with and without libyaml grade with the same data.
    # repr, not ==, because 1 == 1.0 == True in Python but they are different expected values.
    files = sorted(DEFAULT_PROBLEMS_ROOT.rglob("*.yaml"))
    assert len(files) >= 66  # problem.yaml + tests.yaml for every problem
    for path in files:
        text = path.read_text(encoding="utf-8")
        reference = yaml.load(text, Loader=yaml.SafeLoader)
        assert repr(parse_yaml(text)) == repr(reference), f"{path}: the parsers disagree"
