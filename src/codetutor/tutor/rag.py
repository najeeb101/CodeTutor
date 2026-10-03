"""Search the course notes (Week 4 Step 1, docs/tutor.md §2): by meaning, by words, or both.

- `vector`: the question's embedding against every chunk's, by cosine distance (pgvector `<=>`).
- `keyword`: Postgres full-text search for any of the question's words (OR), ranked by
  `ts_rank_cd`. English stemming: "loops" also finds "loop".
- `hybrid`: both result lists merged by reciprocal rank fusion (RRF). A chunk gets
  1 / (60 + rank) from each list it is in, so a chunk that both lists rank well comes first.

With ~40 chunks every search reads the whole table (about a millisecond); an index only helps
at tens of thousands of rows (ideas.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from codetutor.db.models import NoteChunkRow
from codetutor.evals.clients import Embedder

SearchMethod = Literal["vector", "keyword", "hybrid"]
SEARCH_METHODS: tuple[SearchMethod, ...] = ("keyword", "vector", "hybrid")  # simplest first
RRF_K = 60  # the usual RRF constant: it keeps rank 1 from counting far more than rank 2
FUSION_DEPTH = 20  # how many results of each list the hybrid search merges
_WORD = re.compile(r"[a-z0-9]+")


class RetrievalError(Exception):
    """Search can't run: there are no chunks yet, or they were embedded by another model."""


@dataclass(frozen=True)
class Hit:
    """One search result. Lists of hits are sorted best first."""

    chunk_id: str
    note_title: str
    heading: str
    body: str
    content_hash: str
    score: float  # higher is better; the scale depends on the method


def search(
    session: Session,
    query: str,
    *,
    method: SearchMethod = "vector",
    k: int = 3,
    embedder: Embedder | None = None,
) -> list[Hit]:
    """The `k` best chunks for `query`. `vector` and `hybrid` need the embedder of the notes."""
    if method == "keyword":
        return search_keyword(session, query, k=k)
    if method not in ("vector", "hybrid"):
        raise ValueError(f"unknown search method {method!r}; use one of {SEARCH_METHODS}")
    if embedder is None:
        raise ValueError(f"{method} search needs an embedder")
    if method == "vector":
        return search_vector(session, embedder, query, k=k)
    return search_hybrid(session, embedder, query, k=k)


def search_vector(session: Session, embedder: Embedder, query: str, *, k: int = 3) -> list[Hit]:
    """The chunks closest in meaning. Score = cosine similarity (1 = same direction)."""
    _check_stored_model(session, embedder)
    distance = NoteChunkRow.embedding.cosine_distance(embedder.embed_query(query))
    statement = select(NoteChunkRow, distance).order_by(distance, NoteChunkRow.id).limit(k)
    return [_hit(row, 1.0 - value) for row, value in session.execute(statement)]


def search_keyword(session: Session, query: str, *, k: int = 3) -> list[Hit]:
    """Chunks that share words with `query`, best `ts_rank_cd` first. No words, no hits."""
    words = _WORD.findall(query.lower())
    if not words:
        return []
    # Only [a-z0-9] words joined by "|", so the user's text can't add tsquery operators.
    tsquery = func.to_tsquery("english", " | ".join(words))
    document = func.to_tsvector("english", NoteChunkRow.heading + " " + NoteChunkRow.body)
    rank = func.ts_rank_cd(document, tsquery)
    statement = (
        select(NoteChunkRow, rank)
        .where(document.bool_op("@@")(tsquery))
        .order_by(rank.desc(), NoteChunkRow.id)
        .limit(k)
    )
    return [_hit(row, value) for row, value in session.execute(statement)]


def search_hybrid(session: Session, embedder: Embedder, query: str, *, k: int = 3) -> list[Hit]:
    """Vector and keyword results merged by reciprocal rank fusion (score = sum of 1/(60+rank))."""
    ranked_lists = [
        search_vector(session, embedder, query, k=FUSION_DEPTH),
        search_keyword(session, query, k=FUSION_DEPTH),
    ]
    scores: dict[str, float] = {}
    hits: dict[str, Hit] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            hits.setdefault(hit.chunk_id, hit)
    best = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:k]
    return [replace(hits[chunk_id], score=scores[chunk_id]) for chunk_id in best]


def _check_stored_model(session: Session, embedder: Embedder) -> None:
    """Vectors from two different models can't be compared: refuse instead of guessing."""
    models = set(session.scalars(select(NoteChunkRow.embed_model).distinct()))
    if not models:
        raise RetrievalError("no course notes in the database: run `make notes-sync`")
    if models != {embedder.name}:
        raise RetrievalError(
            f"the notes were embedded with {sorted(models)}, the question with "
            f"{embedder.name!r}: run `make notes-sync` with the same embedder"
        )


def _hit(row: NoteChunkRow, score: Any) -> Hit:
    return Hit(row.id, row.note_title, row.heading, row.body, row.content_hash, float(score))
