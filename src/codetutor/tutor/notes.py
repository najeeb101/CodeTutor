"""Course notes for the tutor's search (Week 4 Step 1, docs/tutor.md §2).

The notes are Markdown files in course/notes/, one per module (`03_loops.md`, named like the
problem bank's module folders): an H1 title, then `##` sections. Each section is one **chunk**:
the unit that is embedded, stored in `note_chunks` and found by search.

`load_notes` reads and checks every note and lists every broken rule in one NotesError.
`sync_notes` copies the chunks into Postgres and embeds only new or changed ones; like
`sync_problems`, the caller commits.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from codetutor.db.models import EMBEDDING_DIMENSIONS, NoteChunkRow
from codetutor.evals.clients import Embedder
from codetutor.problems import Problem
from codetutor.problems.loader import load_all
from codetutor.tutor.guardrail import solution_lines, squash

# src/codetutor/tutor/notes.py -> parents[3] is the repository root.
DEFAULT_NOTES_ROOT = Path(__file__).resolve().parents[3] / "course" / "notes"
DEFAULT_EMBEDDER = "ollama/nomic-embed-text"
MIN_SECTIONS = 3
# Words per section. The upper bound keeps a chunk far inside the embedder's 2K-token window
# (and short enough to quote in a prompt); the lower bound avoids pages with nothing to find.
MIN_SECTION_WORDS = 40
MAX_SECTION_WORDS = 350

_FILE_NAME = re.compile(r"^(\d\d)_[a-z]+\.md$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_PYTHON_BLOCK = re.compile(r"^```python\n(.*?)^```", re.M | re.S)


class NotesError(Exception):
    """The notes break one or more rules (all of them are listed in the message)."""


@dataclass(frozen=True)
class NoteChunk:
    """One `##` section of a note."""

    id: str  # "<file stem>#<heading slug>", e.g. "03_loops#for-loops-and-range"
    module: int
    note_title: str
    heading: str
    body: str  # the section's Markdown, without its "## heading" line

    @property
    def content_hash(self) -> str:
        """sha256 of title, heading and body: a changed hash means "embed again"."""
        text = f"{self.note_title}\n{self.heading}\n{self.body}"
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embedding_text(self) -> str:
        """What is embedded: the title and heading give the section its context."""
        return f"{self.note_title} > {self.heading}\n\n{self.body}"


@dataclass
class NotesSyncReport:
    """What a sync did, by chunk id."""

    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)  # new text, or a new embedding model
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)


def slug(heading: str) -> str:
    """'for loops and range' -> 'for-loops-and-range'."""
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def load_notes(
    root: Path | None = None, *, problems: list[Problem] | None = None
) -> list[NoteChunk]:
    """Every chunk of every note under `root`, checked against the rules and the bank.

    `problems` (default: the whole bank) is used for two checks: there is one note per module
    folder, and no note contains a line of any reference solution.
    """
    root = DEFAULT_NOTES_ROOT if root is None else Path(root)
    problems = load_all() if problems is None else problems
    errors: list[str] = []
    chunks: list[NoteChunk] = []
    paths = sorted(root.glob("*.md")) if root.is_dir() else []
    for path in paths:
        chunks += _read_note(path, errors)
    errors += _check_modules(paths, problems)
    errors += _check_no_solution_lines(chunks, problems)
    if errors:
        raise NotesError(f"{len(errors)} problem(s) in {root}:\n- " + "\n- ".join(errors))
    return chunks


def sync_notes(
    session: Session,
    embedder: Embedder,
    root: Path | None = None,
    *,
    problems: list[Problem] | None = None,
) -> NotesSyncReport:
    """Make `note_chunks` match the notes. Only new or changed chunks are embedded.

    A chunk is changed when its text changed or it was embedded by another model. Chunks whose
    section is gone are deleted. `problems` goes to `load_notes`. The caller commits.
    """
    if embedder.dimensions != EMBEDDING_DIMENSIONS:
        raise NotesError(
            f"{embedder.name} gives {embedder.dimensions} numbers per text, but the "
            f"note_chunks column holds {EMBEDDING_DIMENSIONS} (a new size needs a migration)"
        )
    chunks = load_notes(root, problems=problems)
    stored = {row.id: row for row in session.scalars(select(NoteChunkRow))}
    report = NotesSyncReport()
    to_embed: list[NoteChunk] = []
    for chunk in chunks:
        row = stored.get(chunk.id)
        if row is None:
            report.added.append(chunk.id)
            to_embed.append(chunk)
        elif row.content_hash != chunk.content_hash or row.embed_model != embedder.name:
            report.changed.append(chunk.id)
            to_embed.append(chunk)
        else:
            report.unchanged.append(chunk.id)
    texts = [chunk.embedding_text() for chunk in to_embed]
    vectors = embedder.embed_documents(texts) if texts else []
    for chunk, vector in zip(to_embed, vectors, strict=True):
        _store(session, stored.get(chunk.id), chunk, vector, embedder.name)
    report.removed = sorted(set(stored) - {chunk.id for chunk in chunks})
    if report.removed:
        session.execute(delete(NoteChunkRow).where(NoteChunkRow.id.in_(report.removed)))
    return report


def _store(
    session: Session,
    row: NoteChunkRow | None,
    chunk: NoteChunk,
    vector: list[float],
    model: str,
) -> None:
    values = {
        "module": chunk.module,
        "note_title": chunk.note_title,
        "heading": chunk.heading,
        "body": chunk.body,
        "content_hash": chunk.content_hash,
        "embed_model": model,
        "embedding": vector,
    }
    if row is None:
        session.add(NoteChunkRow(id=chunk.id, **values))
        return
    for name, value in values.items():
        setattr(row, name, value)
    row.updated_at = func.now()


def _read_note(path: Path, errors: list[str]) -> list[NoteChunk]:
    """The chunks of one note; broken rules are appended to `errors`."""
    match = _FILE_NAME.match(path.name)
    if not match:
        errors.append(f"{path.name}: the name must look like '03_loops.md'")
        return []
    module = int(match[1])
    lines = path.read_text(encoding="utf-8").splitlines()
    title, sections, before = _split_sections(lines)
    if title is None:
        errors.append(f"{path.name}: the first line must be the title ('# ...')")
        return []
    if before.strip():
        errors.append(f"{path.name}: text before the first '## ' section is never searched")
    if len(sections) < MIN_SECTIONS:
        errors.append(f"{path.name}: {len(sections)} sections, at least {MIN_SECTIONS} needed")
    chunks = [
        NoteChunk(f"{path.stem}#{slug(heading)}", module, title, heading, body.strip())
        for heading, body in sections
    ]
    for chunk in chunks:
        errors += [f"{path.name}, '{chunk.heading}': {error}" for error in _check_chunk(chunk)]
    duplicates = [i for i, n in Counter(chunk.id for chunk in chunks).items() if n > 1]
    errors += [f"{path.name}: two sections have the id {i!r}" for i in duplicates]
    return chunks


def _split_sections(lines: list[str]) -> tuple[str | None, list[tuple[str, str]], str]:
    """(title, [(heading, body)], text before the first section). `##` inside code is body."""
    if not lines or not lines[0].startswith("# "):
        return None, [], ""
    title = lines[0][2:].strip()
    sections: list[tuple[str, list[str]]] = []
    before: list[str] = []
    in_code = False
    for line in lines[1:]:
        if _FENCE.match(line):
            in_code = not in_code
        if line.startswith("## ") and not in_code:
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            before.append(line)
    return title, [(head, "\n".join(body)) for head, body in sections], "\n".join(before)


def _check_chunk(chunk: NoteChunk) -> list[str]:
    errors = []
    words = len(chunk.body.split())
    if not MIN_SECTION_WORDS <= words <= MAX_SECTION_WORDS:
        errors.append(f"{words} words, allowed {MIN_SECTION_WORDS}-{MAX_SECTION_WORDS}")
    for code in _PYTHON_BLOCK.findall(chunk.body):
        try:
            ast.parse(code)
        except SyntaxError as exc:
            errors.append(f"a python example does not parse: {exc.msg} (line {exc.lineno})")
    return errors


def _check_modules(paths: list[Path], problems: list[Problem]) -> list[str]:
    """One note per module folder of the bank, with the same names (e.g. 03_loops)."""
    wanted = {_module_folder(problem) for problem in problems}
    # Badly named files are already reported by _read_note; don't report them twice.
    present = {path.stem for path in paths if _FILE_NAME.match(path.name)}
    errors = [f"no note for module {name} (add {name}.md)" for name in sorted(wanted - present)]
    errors += [f"{name}.md has no module folder in the bank" for name in sorted(present - wanted)]
    return errors


def _module_folder(problem: Problem) -> str:
    """'cs1.loops.fizzbuzz' lives in problems/cs1/03_loops/fizzbuzz: return '03_loops'."""
    _, module_slug, _ = problem.id.split(".")
    return f"{problem.module:02d}_{module_slug}"


def _check_no_solution_lines(chunks: list[NoteChunk], problems: list[Problem]) -> list[str]:
    """A note must never contain a line of a reference solution (the guardrail's rule)."""
    errors = []
    bodies = {chunk.id: squash(chunk.body) for chunk in chunks}
    for problem in problems:
        for line in solution_lines(problem):
            for chunk_id, body in bodies.items():
                if squash(line) in body:
                    errors.append(f"{chunk_id}: contains a line of {problem.id}'s solution: {line}")
    return errors
