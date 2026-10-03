"""Note search and the retrieval eval (Week 4 Step 1), with the fake embedder (no Ollama)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from codetutor.problems import Problem
from codetutor.problems.loader import load_all
from codetutor.tutor.notes import load_notes, sync_notes
from codetutor.tutor.rag import RRF_K, RetrievalError, search
from codetutor.tutor.retrieval_eval import (
    DEFAULT_QUESTIONS,
    MethodResult,
    Question,
    best_method,
    first_relevant_rank,
    hits_at,
    load_questions,
    mean_reciprocal_rank,
    render_report,
    run_eval,
)
from conftest import HashingEmbedder

FILLER = " ".join(["note"] * 40)
SECTIONS = {
    "While loops": f"a while loop never stops when the counter makes no progress. {FILLER}",
    "Splitting text": f"split breaks text into words; join puts words back together. {FILLER}",
    "Counting with a dictionary": f"a dictionary maps each key to a count. {FILLER}",
}
IDS = ["03_loops#while-loops", "03_loops#splitting-text", "03_loops#counting-with-a-dictionary"]


@pytest.fixture(scope="module")
def fizz() -> Problem:
    return {problem.id: problem for problem in load_all()}["cs1.loops.fizzbuzz"]


@pytest.fixture
def notes(db_session: Session, tmp_path: Path, fizz: Problem) -> HashingEmbedder:
    """Three synced sections (in module 03_loops); returns the embedder that indexed them."""
    lines = ["# Loops", ""]
    for heading, body in SECTIONS.items():
        lines += [f"## {heading}", body, ""]
    (tmp_path / "03_loops.md").write_text("\n".join(lines), encoding="utf-8")
    embedder = HashingEmbedder()
    sync_notes(db_session, embedder, tmp_path, problems=[fizz])
    db_session.commit()
    return embedder


def _ids(hits: list) -> list[str]:
    return [hit.chunk_id for hit in hits]


# --- the three methods -------------------------------------------------------------------------


def test_vector_search_ranks_by_meaning(db_session: Session, notes: HashingEmbedder) -> None:
    hits = search(db_session, "my while loop never stops", method="vector", embedder=notes)
    assert _ids(hits)[0] == IDS[0]
    assert len(hits) == 3 and hits[0].score > hits[1].score >= hits[2].score
    assert len(search(db_session, "loop", method="vector", k=1, embedder=notes)) == 1


def test_keyword_search_matches_words_with_stemming(
    db_session: Session, notes: HashingEmbedder
) -> None:
    # "splits" and "joining" are stemmed to the words in the note ("split", "join").
    hits = search(db_session, "it splits, then joining", method="keyword")
    assert _ids(hits) == [IDS[1]]
    assert search(db_session, "the and of", method="keyword") == []  # only stop words
    assert search(db_session, "!!! ???", method="keyword") == []  # no words at all
    # tsquery operators in the question are just dropped, never parsed.
    assert _ids(search(db_session, "dictionary | ! & <-> (", method="keyword")) == [IDS[2]]


def test_hybrid_search_fuses_both_rankings(db_session: Session, notes: HashingEmbedder) -> None:
    hits = search(db_session, "split the words", method="hybrid", embedder=notes)
    assert _ids(hits)[0] == IDS[1]
    # First in both lists: 1/(60 + 1) twice.
    assert hits[0].score == pytest.approx(2 / (RRF_K + 1))


def test_bad_calls_are_refused(db_session: Session, notes: HashingEmbedder) -> None:
    with pytest.raises(ValueError, match="unknown search method"):
        search(db_session, "x", method="magic")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="needs an embedder"):
        search(db_session, "x", method="hybrid")
    with pytest.raises(RetrievalError, match="embedded with \\['fake/hashing'\\]"):
        search(db_session, "x", method="vector", embedder=HashingEmbedder("fake/other"))


def test_vector_search_without_notes_says_what_to_do(db_session: Session) -> None:
    with pytest.raises(RetrievalError, match="make notes-sync"):
        search(db_session, "x", method="vector", embedder=HashingEmbedder())


# --- metrics -----------------------------------------------------------------------------------


def test_ranks_recall_and_mrr() -> None:
    assert first_relevant_rank(["a", "b", "c"], ["c", "x"]) == 3
    assert first_relevant_rank(["a"], ["x"]) is None
    ranks = [1, 3, None, 2]
    assert (hits_at(ranks, 1), hits_at(ranks, 3)) == (1, 3)
    assert mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 3 + 1 / 2) / 4)
    assert mean_reciprocal_rank([]) == 0.0


def test_a_tie_goes_to_the_simplest_method() -> None:
    results = [
        MethodResult("hybrid", [1, 2], [[], []]),
        MethodResult("keyword", [2, 1], [[], []]),
        MethodResult("vector", [1, None], [[], []]),
    ]
    assert best_method(results, k=3).method == "keyword"


# --- the labelled questions --------------------------------------------------------------------


def test_the_labelled_questions_point_at_real_sections() -> None:
    known = {chunk.id for chunk in load_notes()}
    questions = load_questions(DEFAULT_QUESTIONS, known)
    assert len(questions) == 40
    assert [q.style for q in questions].count("symptom") == 25


def test_broken_question_files_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "q.yaml"
    path.write_text(
        "- {question: a, style: concept, relevant: [x#y]}\n"
        "- {question: a, style: vibe, relevant: [x#known]}\n"
        "- {question: b, style: concept}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as error:
        load_questions(path, {"x#known"})
    message = str(error.value)
    assert "#1: relevant must list known chunk ids (unknown: ['x#y'])" in message
    assert "#2: style 'vibe'" in message
    assert "#3: needs exactly the keys" in message
    assert "asked twice: 'a'" in message


def test_the_eval_end_to_end(
    db_session: Session, notes: HashingEmbedder, fizz: Problem, tmp_path: Path
) -> None:
    questions = [
        Question("why does my while loop never stop", "symptom", (IDS[0],)),
        Question("how do I count things with a dictionary", "concept", (IDS[2],)),
    ]
    results = run_eval(db_session, notes, questions)
    assert [result.method for result in results] == ["keyword", "vector", "hybrid"]
    assert all(result.ranks == [1, 1] for result in results)
    chunks = load_notes(tmp_path, problems=[fizz])
    report = render_report(results, questions, chunks, embedder_name=notes.name)
    assert "| vector | 2/2 (1.000) | 2/2 (1.000) | 1.000 |" in report
    assert "Best recall@3: **keyword**" in report
    assert report == render_report(results, questions, chunks, embedder_name=notes.name)
