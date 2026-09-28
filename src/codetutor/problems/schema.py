"""Pydantic models that define what a valid problem is.

Everything that can be checked *without running code* is checked here: types, allowed values,
test counts, unique ids, and that the required function is defined. Checks that need to run code
(the solution passes, buggy solutions fail) belong to the validator (Step 3).
"""

from __future__ import annotations

import ast
import json
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

# Minimum test counts per problem (brief section 1.3).
MIN_TESTS = 8
MIN_VISIBLE_TESTS = 3
MIN_HIDDEN_TESTS = 3
NUM_HINTS = 3
DEFAULT_TIME_LIMIT_S = 2.0

# e.g. "cs1.loops.sum_of_evens" -> <course>.<module_slug>.<problem_slug>
PROBLEM_ID_PATTERN = r"^[a-z][a-z0-9]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
TEST_ID_PATTERN = r"^[a-z0-9_]+$"

# A hint line that starts with a lowercase Python keyword is probably code, not a hint.
# Simple heuristic: it catches "for i in range(n):" but not code written inside a sentence.
_CODE_LINE = re.compile(
    r"^\s*(def|class|return|import|from|for|while|if|elif|else|try|except|with)\b", re.MULTILINE
)


class Difficulty(StrEnum):
    """How hard a problem is meant to be for a CS1 student."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class CompareMode(StrEnum):
    """How the grader compares the actual output with the expected output."""

    EXACT = "exact"
    UNORDERED = "unordered"
    FLOAT = "float"


class Concept(StrEnum):
    """Fixed vocabulary of concepts. Used later for per-concept skill tracking."""

    ARITHMETIC = "arithmetic"
    CONDITIONALS = "conditionals"
    FOR_LOOPS = "for_loops"
    WHILE_LOOPS = "while_loops"
    STRINGS = "strings"
    LISTS = "lists"
    DICTS = "dicts"
    FUNCTIONS = "functions"
    RECURSION = "recursion"
    SORTING = "sorting"
    SEARCHING = "searching"
    EDGE_CASES = "edge_cases"
    EFFICIENCY = "efficiency"


# extra="forbid": an unknown key (e.g. the typo "hiden") is an error instead of being ignored.
# frozen=True: problems are content; nobody should change a loaded problem by accident.
# Note: frozen is shallow. Lists inside (like a test's input) can still be mutated, so code
# that runs tests must deep-copy inputs.
_STRICT = ConfigDict(extra="forbid", frozen=True)


def _ensure_strict_json(value: JsonValue) -> JsonValue:
    """Reject values that JSON cannot represent exactly (NaN and infinity)."""
    try:
        json.dumps(value, allow_nan=False)
    except ValueError as exc:
        raise ValueError("must be JSON-compatible (NaN and infinity are not allowed)") from exc
    return value


def _top_level_functions(code: str, label: str) -> set[str]:
    """Return the names of functions defined at the top level of `code`."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"{label} has a syntax error on line {exc.lineno}: {exc.msg}") from exc
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


class TestCase(BaseModel):
    """One test: call the function with `input` as positional arguments, expect `expected`."""

    model_config = _STRICT
    __test__ = False  # tell pytest this is not a test class, despite the name

    id: Annotated[str, Field(pattern=TEST_ID_PATTERN)]
    input: list[JsonValue]
    # `expected` may be missing before fill_expected.py has run. We can't use None to mean
    # "missing", because None (null) is a real answer for some problems. See `has_expected`.
    expected: JsonValue = None
    hidden: bool  # required on purpose: forgetting it must not silently make a test visible
    compare: CompareMode
    note: str | None = None

    @field_validator("input", "expected")
    @classmethod
    def _json_compatible(cls, value: JsonValue) -> JsonValue:
        return _ensure_strict_json(value)

    @property
    def has_expected(self) -> bool:
        """True if `expected` was written in tests.yaml (even if its value is null)."""
        return "expected" in self.model_fields_set


class VisibleTest(BaseModel):
    """A visible test as shown to students (and to models in evals)."""

    model_config = _STRICT

    id: str
    input: list[JsonValue]
    expected: JsonValue
    compare: CompareMode
    note: str | None = None


class StudentProblem(BaseModel):
    """What a student (or a model being evaluated) is allowed to see.

    No reference solution, no buggy solutions, no hidden tests, no hints.
    """

    model_config = _STRICT

    id: str
    version: int
    title: str
    module: int
    module_name: str
    order: int
    difficulty: Difficulty
    concepts: list[Concept]
    function_name: str
    description_en: str
    description_ar: str | None
    starter_code: str
    time_limit_s: float
    examples: list[VisibleTest]


class Problem(BaseModel):
    """A complete problem (internal view): metadata, code files and all tests."""

    model_config = _STRICT

    # --- from problem.yaml ---
    id: Annotated[str, Field(pattern=PROBLEM_ID_PATTERN)]
    version: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1)]
    module: Annotated[int, Field(ge=1, le=8)]
    module_name: Annotated[str, Field(min_length=1)]
    order: Annotated[int, Field(ge=1)]
    difficulty: Difficulty
    concepts: Annotated[list[Concept], Field(min_length=1)]
    function_name: str
    description_en: Annotated[str, Field(min_length=1)]
    description_ar: str | None = None
    hints: Annotated[list[str], Field(min_length=NUM_HINTS, max_length=NUM_HINTS)]
    time_limit_s: Annotated[float, Field(gt=0, le=10)] = DEFAULT_TIME_LIMIT_S
    author: Literal["najeeb", "claude"]

    # --- from tests.yaml and the .py files ---
    tests: list[TestCase]
    starter_code: str
    solution_code: str
    buggy: dict[str, str] = Field(default_factory=dict)  # {"off_by_one": "<code>", ...}

    @field_validator("function_name")
    @classmethod
    def _valid_identifier(cls, name: str) -> str:
        if not name.isidentifier():
            raise ValueError(f"{name!r} is not a valid Python function name")
        return name

    @field_validator("concepts")
    @classmethod
    def _unique_concepts(cls, concepts: list[Concept]) -> list[Concept]:
        if len(set(concepts)) != len(concepts):
            raise ValueError("concepts must not contain duplicates")
        return concepts

    @field_validator("hints")
    @classmethod
    def _hints_are_not_code(cls, hints: list[str]) -> list[str]:
        for number, hint in enumerate(hints, start=1):
            if "```" in hint or _CODE_LINE.search(hint):
                raise ValueError(f"hint {number} looks like code; hints must be words, not code")
        return hints

    @model_validator(mode="after")
    def _check_tests(self) -> Problem:
        ids = [test.id for test in self.tests]
        duplicates = sorted({test_id for test_id in ids if ids.count(test_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate test ids: {', '.join(duplicates)}")

        visible = sum(1 for test in self.tests if not test.hidden)
        hidden = len(self.tests) - visible
        if len(self.tests) < MIN_TESTS:
            raise ValueError(f"needs at least {MIN_TESTS} tests, found {len(self.tests)}")
        if visible < MIN_VISIBLE_TESTS:
            raise ValueError(f"needs at least {MIN_VISIBLE_TESTS} visible tests, found {visible}")
        if hidden < MIN_HIDDEN_TESTS:
            raise ValueError(f"needs at least {MIN_HIDDEN_TESTS} hidden tests, found {hidden}")
        return self

    @model_validator(mode="after")
    def _check_function_defined(self) -> Problem:
        for label, code in (("starter.py", self.starter_code), ("solution.py", self.solution_code)):
            if self.function_name not in _top_level_functions(code, label):
                raise ValueError(f"{label} does not define a function named {self.function_name!r}")
        return self

    @property
    def visible_tests(self) -> list[TestCase]:
        """Tests the student can see."""
        return [test for test in self.tests if not test.hidden]

    @property
    def hidden_tests(self) -> list[TestCase]:
        """Tests the student never sees; they protect against overfitting to visible tests."""
        return [test for test in self.tests if test.hidden]

    def to_student_view(self) -> StudentProblem:
        """Return only what a student (or a model in an eval) may see."""
        examples = [
            VisibleTest(
                id=test.id,
                input=test.input,
                expected=test.expected,
                compare=test.compare,
                note=test.note,
            )
            for test in self.visible_tests
        ]
        return StudentProblem(
            id=self.id,
            version=self.version,
            title=self.title,
            module=self.module,
            module_name=self.module_name,
            order=self.order,
            difficulty=self.difficulty,
            concepts=self.concepts,
            function_name=self.function_name,
            description_en=self.description_en,
            description_ar=self.description_ar,
            starter_code=self.starter_code,
            time_limit_s=self.time_limit_s,
            examples=examples,
        )
