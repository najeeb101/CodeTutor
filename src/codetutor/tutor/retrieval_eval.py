"""The retrieval eval (Week 4 Step 1): does search find the note section that answers a question?

Labelled questions (lab/tutor/retrieval_questions.yaml) go through each search method; we keep
the rank of the first relevant section and compute:
- recall@k: the share of questions with a relevant section in the top k (k = 1 and 3);
- MRR@10: the mean of 1/rank of the first relevant section (0 if it is not in the top 10).
A Markdown report shows them overall and by question style. Only `run_eval` touches the
database; everything else is a pure function.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from sqlalchemy.orm import Session

from codetutor.evals.clients import Embedder
from codetutor.tutor.notes import NoteChunk
from codetutor.tutor.rag import SEARCH_METHODS, SearchMethod, search

# src/codetutor/tutor/retrieval_eval.py -> parents[3] is the repository root.
_REPO = Path(__file__).resolve().parents[3]
DEFAULT_QUESTIONS = _REPO / "lab" / "tutor" / "retrieval_questions.yaml"
DEFAULT_REPORT = _REPO / "lab" / "tutor" / "reports" / "retrieval.md"
RANK_DEPTH = 10  # MRR looks this deep
STYLES = ("concept", "symptom")

Style = Literal["concept", "symptom"]


@dataclass(frozen=True)
class Question:
    """One labelled question: any of `relevant` (chunk ids) counts as a hit."""

    question: str
    style: Style
    relevant: tuple[str, ...]


@dataclass(frozen=True)
class MethodResult:
    """One method's results, in the same order as the questions."""

    method: SearchMethod
    ranks: list[int | None]  # rank of the first relevant chunk (1 = top), None if not found
    top: list[list[str]]  # the top RANK_DEPTH chunk ids per question


def load_questions(path: Path, known_ids: set[str]) -> list[Question]:
    """Read and check the labelled questions. Every broken rule is listed in one ValueError."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    errors: list[str] = []
    questions: list[Question] = []
    for number, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or set(item) != {"question", "style", "relevant"}:
            errors.append(f"#{number}: needs exactly the keys question, style, relevant")
            continue
        if item["style"] not in STYLES:
            errors.append(f"#{number}: style {item['style']!r} is not one of {STYLES}")
        unknown = [chunk_id for chunk_id in item["relevant"] or [] if chunk_id not in known_ids]
        if not item["relevant"] or unknown:
            errors.append(f"#{number}: relevant must list known chunk ids (unknown: {unknown})")
        questions.append(Question(item["question"], item["style"], tuple(item["relevant"] or [])))
    texts = [question.question for question in questions]
    errors += [f"asked twice: {text!r}" for text in sorted(set(texts)) if texts.count(text) > 1]
    if errors:
        raise ValueError(f"{path}:\n- " + "\n- ".join(errors))
    return questions


def first_relevant_rank(ranked_ids: Sequence[str], relevant: Sequence[str]) -> int | None:
    """1-based rank of the first relevant id, or None."""
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            return rank
    return None


def hits_at(ranks: Sequence[int | None], k: int) -> int:
    """How many questions have a relevant chunk in the top k."""
    return sum(1 for rank in ranks if rank is not None and rank <= k)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    """Mean of 1/rank (0 for "not found"). 1.0 means always first."""
    if not ranks:
        return 0.0
    return sum(1 / rank for rank in ranks if rank is not None) / len(ranks)


def run_eval(
    session: Session,
    embedder: Embedder,
    questions: Sequence[Question],
    methods: Sequence[SearchMethod] = SEARCH_METHODS,
) -> list[MethodResult]:
    """Ask every question with every method and record the ranks."""
    results = []
    for method in methods:
        ranks: list[int | None] = []
        top: list[list[str]] = []
        for question in questions:
            hits = search(
                session, question.question, method=method, k=RANK_DEPTH, embedder=embedder
            )
            ids = [hit.chunk_id for hit in hits]
            ranks.append(first_relevant_rank(ids, question.relevant))
            top.append(ids)
        results.append(MethodResult(method, ranks, top))
    return results


def best_method(results: Sequence[MethodResult], k: int) -> MethodResult:
    """The highest recall@k; on a tie, the simplest (SEARCH_METHODS lists the simplest first)."""
    order = {method: position for position, method in enumerate(SEARCH_METHODS)}
    return max(results, key=lambda result: (hits_at(result.ranks, k), -order[result.method]))


def notes_fingerprint(chunks: Sequence[NoteChunk]) -> str:
    """A short hash of all chunks, so a report shows which version of the notes it measured."""
    joined = "\n".join(sorted(f"{chunk.id} {chunk.content_hash}" for chunk in chunks))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def render_report(
    results: Sequence[MethodResult],
    questions: Sequence[Question],
    chunks: Sequence[NoteChunk],
    *,
    embedder_name: str,
    k: int = 3,
) -> str:
    """The Markdown report. The same inputs always give the same text (no dates)."""
    total = len(questions)
    by_style = {style: [i for i, q in enumerate(questions) if q.style == style] for style in STYLES}
    notes = len({chunk.id.split("#")[0] for chunk in chunks})
    lines = [
        "# Retrieval eval",
        "",
        "Generated by `scripts/eval_retrieval.py` (docs/tutor.md §2). Do not edit by hand.",
        "",
        f"- Notes: {len(chunks)} sections from {notes} notes in `course/notes/` "
        f"(fingerprint `{notes_fingerprint(chunks)}`).",
        f"- Questions: {total} ("
        + ", ".join(f"{len(index)} {style}" for style, index in by_style.items())
        + ") from `lab/tutor/retrieval_questions.yaml`.",
        f"- Embedder: `{embedder_name}`. A hit = any relevant section in the top k.",
        "",
        f"| Method | recall@1 | recall@{k} | MRR@{RANK_DEPTH} |",
        "|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {result.method} | {_share(hits_at(result.ranks, 1), total)} "
            f"| {_share(hits_at(result.ranks, k), total)} "
            f"| {mean_reciprocal_rank(result.ranks):.3f} |"
        )
    lines += ["", f"## recall@{k} by question style", ""]
    lines.append("| Method | " + " | ".join(f"{s} ({len(i)})" for s, i in by_style.items()) + " |")
    lines.append("|---|" + "---|" * len(by_style))
    for result in results:
        cells = [
            _share(hits_at([result.ranks[i] for i in index], k), len(index))
            for index in by_style.values()
        ]
        lines.append(f"| {result.method} | " + " | ".join(cells) + " |")
    best = best_method(results, k)
    lines += ["", f"Best recall@{k}: **{best.method}** (on a tie, the simplest method).", ""]
    for result in results:
        lines += _misses(result, questions, k)
    return "\n".join(lines) + "\n"


def _misses(result: MethodResult, questions: Sequence[Question], k: int) -> list[str]:
    """A table of the questions `result` missed at k (or "None.")."""
    misses = [i for i, rank in enumerate(result.ranks) if rank is None or rank > k]
    lines = [f"## Misses of {result.method} at k = {k}", ""]
    if not misses:
        return [*lines, "None.", ""]
    lines += [f"| Question | Style | Wanted | Found (top {k}) |", "|---|---|---|---|"]
    for i in misses:
        question = questions[i]
        wanted = ", ".join(f"`{chunk_id}`" for chunk_id in question.relevant)
        found = ", ".join(f"`{chunk_id}`" for chunk_id in result.top[i][:k])
        text = question.question.replace("|", "\\|")
        lines.append(f"| {text} | {question.style} | {wanted} | {found} |")
    return [*lines, ""]


def _share(count: int, total: int) -> str:
    """'37/40 (0.925)': the count, and the share with 3 decimals (no rounding surprises)."""
    return f"{count}/{total} ({count / total:.3f})" if total else "–"
