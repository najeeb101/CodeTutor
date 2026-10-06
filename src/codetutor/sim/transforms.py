"""Disguises for code (Week 5 Step 1): rename variables, reformat. Behaviour never changes.

The simulated class uses them two ways: an honest student picks their own variable names
("own style"), and a copier disguises someone else's code. Step 2's copy detector must see
through both, so both have to be realistic, and a test grades the results to prove the code
still does the same thing.

Renaming edits the exact places Python's parser reports, so formatting and comments stay.
Reformatting prints the parsed code back (`ast.unparse`), which also drops the comments.
"""

from __future__ import annotations

import ast
import builtins
import keyword
import random

# Names a CS1 student might pick. Renaming takes fresh ones from here first.
STUDENT_NAMES = (
    "x", "y", "z", "a", "b", "c", "i", "j", "k", "n", "m", "s", "t", "num", "nums", "number",
    "numbers", "val", "value", "values", "total", "result", "res", "count", "cnt", "temp",
    "tmp", "item", "items", "word", "words", "text", "char", "ch", "key", "out", "ans",
    "answer", "acc", "cur", "current", "prev", "left", "right", "lo", "hi", "mid", "seen",
    "lst", "arr", "data", "found", "idx", "index", "pos", "best", "size", "length", "parts",
    "piece", "letter", "letters", "digit", "digits", "sub", "rest", "first", "last", "pair",
)  # fmt: skip

_RESERVED = frozenset(dir(builtins)) | frozenset(keyword.kwlist) | frozenset(keyword.softkwlist)


def renamable_names(code: str, function_name: str) -> list[str]:
    """The variable and parameter names `code` defines that can be renamed safely, sorted.

    Left alone: builtins (renaming `len` would break it), the graded function's name, names of
    other functions and classes, imported names, names in `global`/`nonlocal`, exception
    names, and any name also used as a keyword argument (`f(key=...)` would stop matching).
    """
    tree = ast.parse(code)
    bound: set[str] = set()
    keep: set[str] = {function_name}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            keep.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            keep.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            keep.update(node.names)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            keep.add(node.name)
        elif isinstance(node, ast.keyword) and node.arg:
            keep.add(node.arg)
    return sorted(bound - keep - _RESERVED)


def _all_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return names


def rename_identifiers(code: str, function_name: str, rng: random.Random) -> str:
    """`code` with its renamable names replaced by fresh student-like names (same behaviour).

    Every occurrence of a name gets the same new name, and a new name never collides with any
    name already in the code, a builtin or a keyword, so the program means exactly the same.
    """
    tree = ast.parse(code)
    old_names = renamable_names(code, function_name)
    taken = _all_names(tree) | _RESERVED
    candidates = [name for name in STUDENT_NAMES if name not in taken]
    rng.shuffle(candidates)
    mapping: dict[str, str] = {}
    for number, old in enumerate(old_names):
        new = candidates.pop() if candidates else f"v{number}"
        while new in taken:  # only possible for the v<number> fallback
            new += "_"
        mapping[old] = new
        taken.add(new)

    # (line, start column, end column, new name); columns are UTF-8 byte offsets (ast's unit).
    edits: list[tuple[int, int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in mapping:
            edits.append((node.lineno, node.col_offset, node.end_col_offset, mapping[node.id]))
        elif isinstance(node, ast.arg) and node.arg in mapping:
            start = node.col_offset  # the arg node starts with its name
            edits.append((node.lineno, start, start + len(node.arg.encode()), mapping[node.arg]))
    lines = code.splitlines(keepends=True)
    for line_no, start, end, new in sorted(edits, reverse=True):  # right to left: offsets stay
        raw = lines[line_no - 1].encode()
        lines[line_no - 1] = (raw[:start] + new.encode() + raw[end:]).decode()
    renamed = "".join(lines)
    ast.parse(renamed)  # a broken edit would be a bug here, never a "student mistake"
    return renamed


def reformat(code: str) -> str:
    """`code` printed back from its syntax tree: normalized spacing and quotes, no comments."""
    return ast.unparse(ast.parse(code)) + "\n"
