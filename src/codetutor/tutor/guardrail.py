"""Output guardrail for tutor hints: does a hint give away code or the solution? (Week 4)

A hint must be words, not code. `check_hint` returns the reasons a hint must not be shown; an
empty list means it is OK. Three rules (docs/tutor.md §1 has the measured numbers):

- `solution_line`: a non-trivial line of solution.py is in the hint (spaces and quote style
  ignored). Trivial lines like `count = 0`, `return result` or `for word in words:` say
  nothing about the answer.
- `code_block`: a fenced block, or 2+ lines in a row that are Python (at least one statement).
- `code_statement`: a single such line, or a `backtick` span that is a statement. Expressions
  stay allowed (`number % 15 == 0`): the reference hints use them.

Text that is also in the starter code, the description or the student's own code is always
allowed: quoting a student's own line back to them is good tutoring.

This compares text and parses code; it does not understand meaning. An algorithm told in plain
words passes on purpose (hints are words), and so does code written inside a sentence unless it
is a line of the solution. The tutor model never sees solution.py, but it can solve most
problems by itself, so this check is needed anyway.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from dataclasses import dataclass
from typing import Literal

from codetutor.problems import Problem

ViolationKind = Literal["solution_line", "code_block", "code_statement"]

MAX_DETAIL_CHARS = 200

# A solution line that says nothing about the answer: return a name or a constant, give a name
# a simple value (`count = 0`, `i += 1`, `result = []`), or a header made of plain words
# (`for word in words:`). Matched against the line with single spaces, so word gaps survive.
_VALUE = r"""(?:[\w"'.-]+|\[\]|\{\}|\(\))"""
_TRIVIAL_LINE = re.compile(
    rf"""^(?:
        return\ {_VALUE}
      | \w+\ (?:=|\+=|-=)\ {_VALUE}
      | (?:else|try|finally):
      | (?:for|if|elif|while)\ [\w\ ]+:
    )$""",
    re.VERBOSE,
)
# A fence (``` or ~~~), an optional language name on its own line, the body, and the closing
# fence (or the end of the text if it is missing). Also matches ```x = 1``` inside a sentence.
_FENCED_BLOCK = re.compile(r"(```|~~~)(?:[\w+-]*\n)?(.*?)(?:\1|\Z)", re.S)
_BACKTICK_SPAN = re.compile(r"(?<!`)`([^`\n]+)`(?!`)")
_LIST_MARKER = re.compile(r"^(?:[-*+]|\d+[.)])\s+")


@dataclass(frozen=True)
class Violation:
    """One reason a hint must not be shown. `detail` is for traces, never for the student."""

    kind: ViolationKind
    detail: str


def check_hint(text: str, problem: Problem, *, student_code: str = "") -> list[Violation]:
    """Every reason `text` must not be shown as a hint for `problem` (empty list = OK)."""
    allowed = squash(problem.starter_code + problem.description_en + student_code)
    violations = _solution_lines_in(text, problem, student_code)
    for match in _FENCED_BLOCK.finditer(text):
        violations += _fenced_block(match.group(2), allowed)
    outside = _FENCED_BLOCK.sub("\n", text)
    violations += _code_lines(outside, allowed)
    violations += _backtick_statements(outside, allowed)
    return violations


def solution_lines(problem: Problem) -> list[str]:
    """The solution's own lines that say something about the answer (single-spaced, sorted).

    Left out: empty lines, comments (also at the end of a line), docstrings, trivial lines, and
    lines that are also in the starter code or the description (e.g. the `def` line). Also used
    by the e2e checks.
    """
    allowed = squash(problem.starter_code + problem.description_en)
    lines = set()
    for raw in _without_comments(problem.solution_code):
        line = " ".join(raw.split())
        if not line or line.startswith(("#", '"""', "'''")) or _TRIVIAL_LINE.match(line):
            continue
        if squash(line) not in allowed:
            lines.add(line)
    return sorted(lines)


def _without_comments(code: str) -> list[str]:
    """The lines of `code` with `# comments` cut off. A `#` inside a string stays.

    `code` must be valid Python (the validator checks every solution compiles).
    """
    lines = code.splitlines()
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type == tokenize.COMMENT:
            row, column = token.start
            lines[row - 1] = lines[row - 1][:column]
    return lines


def without_comments(code: str) -> str:
    """`code` with its `# comments` removed; lines that held only a comment are dropped.

    A `#` inside a string stays. Used for the bank's buggy files, whose comments explain the
    bug: a real student's code doesn't. `code` must be valid Python.
    """
    original = code.splitlines()
    cut = _without_comments(code)
    kept = [
        line.rstrip()
        for line, old in zip(cut, original, strict=True)
        if line.strip() or not old.strip()
    ]
    return "\n".join(kept) + "\n"


def squash(text: str) -> str:
    """`text` without whitespace and with one quote style, so `x = 'a'` matches `x="a"`.

    The one comparison for "does this text contain that code line?" (also used by the notes).
    """
    return re.sub(r"\s+", "", text).replace("'", '"')


def _cut(text: str) -> str:
    text = text.strip()
    return text if len(text) <= MAX_DETAIL_CHARS else text[:MAX_DETAIL_CHARS] + "…"


def _solution_lines_in(text: str, problem: Problem, student_code: str) -> list[Violation]:
    squashed, own = squash(text), squash(student_code)
    return [
        Violation("solution_line", line)
        for line in solution_lines(problem)
        if squash(line) in squashed and squash(line) not in own
    ]


def _fenced_block(body: str, allowed: str) -> list[Violation]:
    """A fence is fine only if every line in it is allowed text (e.g. the student's code)."""
    lines = [line for line in body.splitlines() if line.strip()]
    if all(squash(line) in allowed for line in lines):
        return []
    return [Violation("code_block", _cut(body))]


def _python_kind(fragment: str) -> Literal["statement", "expression"] | None:
    """Does `fragment` parse as Python, and is it more than an expression?"""
    text = _LIST_MARKER.sub("", fragment.strip())
    if text.endswith(":"):
        text += " pass"  # a header like `for x in y:` needs a body to parse
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    if not tree.body:
        return None
    if all(_reads_like_prose(node) for node in tree.body):
        return "expression"
    return "statement"


def _reads_like_prose(node: ast.stmt) -> bool:
    """An expression, or an annotation without a value (`Example: fizzbuzz(15)` is prose)."""
    if isinstance(node, ast.Expr):
        return True
    return isinstance(node, ast.AnnAssign) and node.value is None


def _code_lines(text: str, allowed: str) -> list[Violation]:
    """Unfenced code: a statement line, plus the Python lines right after it.

    One line is a `code_statement`; two or more in a row are a `code_block`. A run starts only
    at a statement, because a lone expression line ("Yes", "fizzbuzz(15)") is often prose.
    """
    violations: list[Violation] = []
    run: list[str] = []
    for line in [*text.splitlines(), ""]:  # the empty line at the end closes the last run
        kind = None if squash(line) in allowed else _python_kind(line)
        if kind == "statement" or (kind == "expression" and run):
            run.append(line)
            continue
        if run:
            name: ViolationKind = "code_block" if len(run) >= 2 else "code_statement"
            violations.append(Violation(name, _cut("\n".join(run))))
        run = []
    return violations


def _backtick_statements(text: str, allowed: str) -> list[Violation]:
    return [
        Violation("code_statement", _cut(span))
        for span in _BACKTICK_SPAN.findall(text)
        if _python_kind(span) == "statement" and squash(span) not in allowed
    ]
