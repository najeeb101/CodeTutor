"""Rename-proof code comparison (Week 5 Step 2b, docs/integrity.md §2).

`canonical` prints code back from its syntax tree with every variable renamed to v0, v1, ...
in order of first appearance, and without comments, docstrings or type hints. Two programs
that differ only in names, spacing, quotes or comments get the same text, so the disguises of
`sim/transforms.py` (rename, reformat) don't hide a copy.

`similarity` compares two canonical texts by their token 4-grams (runs of 4 tokens, like
4-word phrases): shared 4-grams / all 4-grams (Jaccard). 1.0 = the same structure.
"""

from __future__ import annotations

import ast
import builtins
import io
import keyword
import tokenize

# Names that keep their meaning in every program: renaming `len` or `True` would hide a
# difference, not a disguise.
_FIXED = frozenset(dir(builtins)) | frozenset(keyword.kwlist) | frozenset(keyword.softkwlist)

GRAM = 4  # tokens per run; short enough for 3-line CS1 programs to have several


def canonical(code: str, function_name: str) -> str | None:
    """`code` with names, layout, comments, docstrings and type hints made uniform.

    The graded function keeps its name (every submission has it), builtins and imported names
    keep theirs. Returns None when the code doesn't parse: there is no structure to compare.
    """
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):  # ValueError: e.g. a NUL character in the source
        return None
    _drop_docstrings_and_hints(tree)
    keep = _FIXED | {function_name} | _imported_names(tree)
    names: dict[str, str] = {}

    def rename(name: str) -> str:
        if name in keep:
            return name
        return names.setdefault(name, f"v{len(names)}")

    # ast.walk visits the tree in a fixed order, so the same structure gives the same numbers.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            node.id = rename(node.id)
        elif isinstance(node, ast.arg):
            node.arg = rename(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node.name = rename(node.name)  # helper functions too; the graded one is kept
    return ast.unparse(tree)


def _drop_docstrings_and_hints(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and _is_text(body[0].value):
                node.body = body[1:] or [ast.Pass()]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.returns = None
        elif isinstance(node, ast.arg):
            node.annotation = None
    # `x: int = 0` becomes `x = 0`; a bare `x: int` declares nothing and goes.
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if isinstance(statements, list) and statements:
                kept = [_without_annotation(s) for s in statements]
                setattr(node, field, [s for s in kept if s is not None] or [ast.Pass()])


def _without_annotation(statement: ast.stmt) -> ast.stmt | None:
    if not isinstance(statement, ast.AnnAssign):
        return statement
    if statement.value is None:
        return None
    return ast.Assign(targets=[statement.target], value=statement.value, lineno=statement.lineno)


def _is_text(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _imported_names(tree: ast.Module) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    return found


def fingerprints(text: str) -> frozenset[tuple[str, ...]]:
    """The set of token 4-grams of a canonical text (a shorter text: one gram of everything)."""
    skip = {tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER}
    tokens = [
        token.string or tokenize.tok_name[token.type]  # INDENT/DEDENT/NEWLINE count as tokens
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type not in skip
    ]
    if len(tokens) <= GRAM:
        return frozenset({tuple(tokens)})
    return frozenset(tuple(tokens[i : i + GRAM]) for i in range(len(tokens) - GRAM + 1))


def similarity(a: frozenset[tuple[str, ...]], b: frozenset[tuple[str, ...]]) -> float:
    """Jaccard overlap of two fingerprint sets: 1.0 = identical, 0.0 = nothing shared."""
    if a == b:
        return 1.0
    return len(a & b) / len(a | b)
