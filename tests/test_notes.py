"""Course notes (Week 4 Step 1): the note rules, the sync into Postgres, and the vector column."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from codetutor.db.models import EMBEDDING_DIMENSIONS, NoteChunkRow
from codetutor.db.vector import from_text, to_text
from codetutor.problems import Problem
from codetutor.problems.loader import load_all
from codetutor.tutor.notes import NoteChunk, NotesError, load_notes, slug, sync_notes
from conftest import HashingEmbedder

WORDS = " ".join(["word"] * 50)  # a section body long enough for the rules


@pytest.fixture(scope="module")
def fizz() -> Problem:
    """The real fizzbuzz problem: module folder 03_loops, with a known solution."""
    return {problem.id: problem for problem in load_all()}["cs1.loops.fizzbuzz"]


def write_note(folder: Path, name: str, sections: dict[str, str], title: str = "Loops") -> Path:
    """Write `name` with an H1 title and one `##` section per item."""
    folder.mkdir(parents=True, exist_ok=True)
    parts = [f"# {title}", ""]
    for heading, body in sections.items():
        parts += [f"## {heading}", body, ""]
    path = folder / name
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def three_sections(**changes: str) -> dict[str, str]:
    sections = {"First idea": f"one {WORDS}", "Second idea": f"two {WORDS}", "Third": WORDS}
    sections.update(changes)
    return sections


# --- the real notes ----------------------------------------------------------------------------


def test_the_course_notes_follow_the_rules() -> None:
    chunks = load_notes()  # raises NotesError if any rule is broken
    modules = [chunk.module for chunk in chunks]
    assert sorted(set(modules)) == list(range(1, 9))
    assert all(modules.count(module) >= 3 for module in set(modules))
    assert len({chunk.id for chunk in chunks}) == len(chunks) == 41


# --- reading one note --------------------------------------------------------------------------


def test_chunks_have_ids_hashes_and_context(tmp_path: Path, fizz: Problem) -> None:
    write_note(tmp_path, "03_loops.md", three_sections())
    first, second, third = load_notes(tmp_path, problems=[fizz])
    assert (first.id, first.module, first.heading) == ("03_loops#first-idea", 3, "First idea")
    assert first.embedding_text().startswith("Loops > First idea\n\none word")
    assert len(first.content_hash) == 64 and first.content_hash != second.content_hash
    edited = NoteChunk(first.id, 3, first.note_title, first.heading, first.body + "!")
    assert edited.content_hash != first.content_hash


def test_slugs_are_plain(fizz: Problem) -> None:
    assert slug("sort() vs sorted()") == "sort-vs-sorted"
    assert (
        slug("Order matters: most specific case first") == "order-matters-most-specific-case-first"
    )


def test_a_heading_inside_a_code_block_is_part_of_the_body(tmp_path: Path, fizz: Problem) -> None:
    code = f"{WORDS}\n```python\n## not a heading\nx = 1\n```"
    write_note(tmp_path, "03_loops.md", three_sections(Third=code))
    chunks = load_notes(tmp_path, problems=[fizz])
    assert len(chunks) == 3 and "## not a heading" in chunks[2].body


def test_every_broken_rule_is_listed(tmp_path: Path, fizz: Problem) -> None:
    bad = {"Short": "too few words", "Bad code": f"{WORDS}\n```python\nif x\n```"}
    path = write_note(tmp_path, "03_loops.md", bad)
    path.write_text(path.read_text().replace("# Loops\n", "# Loops\nan intro\n"))
    write_note(tmp_path, "loops.md", three_sections())
    write_note(tmp_path, "04_strings.md", three_sections())
    with pytest.raises(NotesError) as error:
        load_notes(tmp_path, problems=[fizz])
    message = str(error.value)
    for expected in [
        "03_loops.md: text before the first '## ' section is never searched",
        "03_loops.md: 2 sections, at least 3 needed",
        "'Short': 3 words, allowed 40-350",
        "'Bad code': a python example does not parse",
        "loops.md: the name must look like '03_loops.md'",
        "04_strings.md has no module folder in the bank",
    ]:
        assert expected in message
    assert message.startswith("6 problem(s)")


def test_a_missing_title_a_missing_note_and_twin_headings(tmp_path: Path, fizz: Problem) -> None:
    write_note(tmp_path / "a", "03_loops.md", three_sections(Third=WORDS)).write_text(WORDS)
    with pytest.raises(NotesError, match="the first line must be the title"):
        load_notes(tmp_path / "a", problems=[fizz])
    with pytest.raises(NotesError, match="no note for module 03_loops"):
        load_notes(tmp_path / "empty", problems=[fizz])
    sections = three_sections()
    path = write_note(tmp_path / "b", "03_loops.md", sections)
    path.write_text(path.read_text().replace("## Second idea", "## First idea"))
    with pytest.raises(NotesError, match="two sections have the id '03_loops#first-idea'"):
        load_notes(tmp_path / "b", problems=[fizz])


def test_a_line_of_a_bank_solution_is_refused(tmp_path: Path, fizz: Problem) -> None:
    # Spaces and quote style don't hide it (the guardrail's comparison).
    leak = f"{WORDS}\n\nThen write result.append( 'FizzBuzz' ) there."
    write_note(tmp_path, "03_loops.md", three_sections(Third=leak))
    with pytest.raises(NotesError, match=r"cs1\.loops\.fizzbuzz's solution: result\.append"):
        load_notes(tmp_path, problems=[fizz])


# --- sync into Postgres ------------------------------------------------------------------------


def _stored(session: Session) -> dict[str, NoteChunkRow]:
    return {row.id: row for row in session.scalars(select(NoteChunkRow))}


def test_sync_adds_then_leaves_everything_unchanged(
    db_session: Session, tmp_path: Path, fizz: Problem
) -> None:
    write_note(tmp_path, "03_loops.md", three_sections())
    embedder = HashingEmbedder()
    first = sync_notes(db_session, embedder, tmp_path, problems=[fizz])
    db_session.commit()
    assert len(first.added) == 3 and embedder.calls == [3]

    second = sync_notes(db_session, embedder, tmp_path, problems=[fizz])
    assert (len(second.unchanged), second.added, second.changed, second.removed) == (3, [], [], [])
    assert embedder.calls == [3]  # nothing new to embed: no call at all

    row = _stored(db_session)["03_loops#first-idea"]
    want = embedder.embed_query(row.note_title + " > " + row.heading + "\n\n" + row.body)
    assert len(row.embedding) == EMBEDDING_DIMENSIONS
    # pgvector keeps 4-byte floats: equal up to rounding.
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(row.embedding, want, strict=True))


def test_sync_embeds_changed_chunks_and_deletes_removed_ones(
    db_session: Session, tmp_path: Path, fizz: Problem
) -> None:
    write_note(tmp_path, "03_loops.md", three_sections())
    embedder = HashingEmbedder()
    sync_notes(db_session, embedder, tmp_path, problems=[fizz])
    db_session.commit()
    sections = three_sections(**{"Second idea": f"changed {WORDS}"})
    del sections["Third"]
    sections["Fourth"] = WORDS
    write_note(tmp_path, "03_loops.md", sections)
    report = sync_notes(db_session, embedder, tmp_path, problems=[fizz])
    db_session.commit()
    assert report.changed == ["03_loops#second-idea"]
    assert report.added == ["03_loops#fourth"] and report.removed == ["03_loops#third"]
    assert embedder.calls == [3, 2]
    assert set(_stored(db_session)) == {
        "03_loops#first-idea",
        "03_loops#second-idea",
        "03_loops#fourth",
    }
    assert _stored(db_session)["03_loops#second-idea"].body.startswith("changed")


def test_a_new_embedding_model_embeds_everything_again(
    db_session: Session, tmp_path: Path, fizz: Problem
) -> None:
    write_note(tmp_path, "03_loops.md", three_sections())
    sync_notes(db_session, HashingEmbedder("fake/a"), tmp_path, problems=[fizz])
    db_session.commit()
    report = sync_notes(db_session, HashingEmbedder("fake/b"), tmp_path, problems=[fizz])
    assert len(report.changed) == 3
    assert {row.embed_model for row in _stored(db_session).values()} == {"fake/b"}


def test_a_wrong_vector_size_is_refused(db_session: Session, tmp_path: Path, fizz: Problem) -> None:
    write_note(tmp_path, "03_loops.md", three_sections())
    with pytest.raises(NotesError, match="needs a migration"):
        sync_notes(db_session, HashingEmbedder(dimensions=4), tmp_path, problems=[fizz])


# --- the vector column -------------------------------------------------------------------------


def test_vector_text_form() -> None:
    assert to_text([0.5, -1, 2.25]) == "[0.5,-1.0,2.25]"
    assert from_text("[0.5,-1,2.25]") == [0.5, -1.0, 2.25]
    assert from_text("[]") == []
    with pytest.raises(ValueError, match="needs 3"):
        to_text([1.0, 2.0], dimensions=3)
    with pytest.raises(ValueError, match="NaN"):
        to_text([math.nan])
