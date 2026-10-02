"""Load problems from folders on disk into validated `Problem` objects.

A problem folder looks like:

    problems/<course>/<NN>_<module_slug>/<problem_slug>/
        problem.yaml  tests.yaml  starter.py  solution.py  buggy/*.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from codetutor.problems.schema import Problem

# src/codetutor/problems/loader.py -> parents[3] is the repository root.
DEFAULT_PROBLEMS_ROOT = Path(__file__).resolve().parents[3] / "problems"

# libyaml's C parser reads the bank 7x faster than PyYAML's pure-Python one (measured
# 2026-10-02) and gives the same data (a test compares both on every bank file).
# Machines without libyaml fall back to the pure-Python parser.
_YAML_LOADER = yaml.CSafeLoader if yaml.__with_libyaml__ else yaml.SafeLoader


class ProblemError(Exception):
    """Base class for all problem-related errors."""


class ProblemLoadError(ProblemError):
    """A problem folder is missing a file or contains invalid content."""


class ProblemNotFoundError(ProblemError):
    """No problem with the requested id exists."""


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ProblemLoadError(f"{path}: file is missing")
    return path.read_text(encoding="utf-8")


def parse_yaml(text: str) -> Any:
    """Parse YAML text into plain data (never Python objects), with the fast parser if present."""
    return yaml.load(text, Loader=_YAML_LOADER)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        data = parse_yaml(_read_text(path))
    except yaml.YAMLError as exc:
        raise ProblemLoadError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ProblemLoadError(f"{path}: expected a mapping (key: value pairs) at the top level")
    return data


def _read_buggy(folder: Path) -> dict[str, str]:
    buggy_dir = folder / "buggy"
    if not buggy_dir.is_dir():
        return {}
    return {path.stem: _read_text(path) for path in sorted(buggy_dir.glob("*.py"))}


def _format_validation_error(folder: Path, error: ValidationError) -> str:
    """Turn a pydantic error into readable lines.

    Example line: "tests.yaml: tests[3].hidden: Field required"
    """
    lines = []
    for item in error.errors():
        location = item["loc"]
        # Fields that come from tests.yaml vs problem.yaml, so the message names the right file.
        source = "tests.yaml" if location and location[0] == "tests" else "problem.yaml"
        path = ".".join(f"[{part}]" if isinstance(part, int) else str(part) for part in location)
        path = path.replace(".[", "[")
        where = f"{source}: {path}" if path else source
        lines.append(f"  {where}: {item['msg']}")
    return f"{folder}: invalid problem\n" + "\n".join(lines)


def _check_id_matches_folder(problem: Problem, folder: Path) -> None:
    """Check that the problem's id and module number agree with where its folder is.

    Example: folder  problems/cs1/03_loops/sum_of_evens
             needs   id == "cs1.loops.sum_of_evens"  and  module == 3

    Raise ProblemLoadError (message starting with the folder path) if they don't match.
    """
    course = folder.parent.parent.name  # "cs1"
    module_folder = folder.parent.name  # "03_loops"
    problem_slug = folder.name  # "sum_of_evens"

    number, separator, module_slug = module_folder.partition("_")  # "03", "_", "loops"
    if not separator or not number.isdigit() or not module_slug:
        raise ProblemLoadError(
            f"{folder}: module folder {module_folder!r} must look like 'NN_<module>' "
            "(e.g. '03_loops')"
        )

    expected_id = f"{course}.{module_slug}.{problem_slug}"
    if problem.id != expected_id:
        raise ProblemLoadError(
            f"{folder}: id is {problem.id!r} but the folder says it should be {expected_id!r}"
        )
    if problem.module != int(number):
        raise ProblemLoadError(
            f"{folder}: module is {problem.module} but the folder {module_folder!r} "
            f"says {int(number)}"
        )


def load_problem(path: Path, *, require_expected: bool = True) -> Problem:
    """Load and validate one problem folder.

    Set `require_expected=False` only for tools that fill in expected values (fill_expected.py).
    """
    folder = Path(path)
    if not folder.is_dir():
        raise ProblemLoadError(f"{folder}: not a directory")

    meta = _read_yaml_mapping(folder / "problem.yaml")
    tests_file = _read_yaml_mapping(folder / "tests.yaml")
    if set(tests_file) != {"tests"}:
        raise ProblemLoadError(f"{folder / 'tests.yaml'}: must contain exactly one key, 'tests'")

    data = {
        **meta,
        "tests": tests_file["tests"],
        "starter_code": _read_text(folder / "starter.py"),
        "solution_code": _read_text(folder / "solution.py"),
        "buggy": _read_buggy(folder),
    }
    try:
        problem = Problem.model_validate(data)
    except ValidationError as exc:
        raise ProblemLoadError(_format_validation_error(folder, exc)) from exc

    _check_id_matches_folder(problem, folder)

    if require_expected:
        missing = [test.id for test in problem.tests if not test.has_expected]
        if missing:
            raise ProblemLoadError(
                f"{folder / 'tests.yaml'}: tests without 'expected': {', '.join(missing)} "
                "(run scripts/fill_expected.py)"
            )
    return problem


def find_problem_folders(root: Path | None = None) -> list[Path]:
    """Return every folder under `root` that contains a problem.yaml, sorted by path."""
    root = DEFAULT_PROBLEMS_ROOT if root is None else Path(root)
    if not root.is_dir():
        raise ProblemLoadError(f"{root}: problems root directory not found")
    return [meta_file.parent for meta_file in sorted(root.rglob("problem.yaml"))]


def load_all(root: Path | None = None, *, require_expected: bool = True) -> list[Problem]:
    """Load every problem under `root`, sorted by module then order.

    Raises ProblemLoadError if any problem is invalid or two problems share an id or a
    (module, order) position.
    """
    root = DEFAULT_PROBLEMS_ROOT if root is None else Path(root)
    problems = [
        load_problem(folder, require_expected=require_expected)
        for folder in find_problem_folders(root)
    ]

    seen_ids: set[str] = set()
    seen_positions: dict[tuple[int, int], str] = {}
    for problem in problems:
        if problem.id in seen_ids:
            raise ProblemLoadError(f"{root}: duplicate problem id {problem.id!r}")
        seen_ids.add(problem.id)
        position = (problem.module, problem.order)
        if position in seen_positions:
            raise ProblemLoadError(
                f"{root}: {problem.id!r} and {seen_positions[position]!r} both have "
                f"module {problem.module}, order {problem.order}"
            )
        seen_positions[position] = problem.id

    return sorted(problems, key=lambda problem: (problem.module, problem.order))


def get_problem(
    problem_id: str, root: Path | None = None, *, require_expected: bool = True
) -> Problem:
    """Return the problem with this id, or raise ProblemNotFoundError."""
    for problem in load_all(root, require_expected=require_expected):
        if problem.id == problem_id:
            return problem
    raise ProblemNotFoundError(f"no problem with id {problem_id!r}")
