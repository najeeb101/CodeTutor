"""Measure the note search: recall@1, recall@3 and MRR for each method (Week 4, docs/tutor.md §2).

Usage (after `make notes-sync`; Ollama must be running):
    python scripts/eval_retrieval.py
    python scripts/eval_retrieval.py --k 5 --out lab/tutor/reports/scratch.md

Writes lab/tutor/reports/retrieval.md and prints it. Refuses to run when the database does not
hold exactly the current notes, so a report never describes an older version.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.db.models import NoteChunkRow
from codetutor.evals.clients import ModelError, make_embedder
from codetutor.tutor.notes import DEFAULT_EMBEDDER, load_notes
from codetutor.tutor.retrieval_eval import (
    DEFAULT_QUESTIONS,
    DEFAULT_REPORT,
    load_questions,
    render_report,
    run_eval,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER)
    parser.add_argument("--k", type=int, default=3, help="the k of recall@k in the report")
    args = parser.parse_args()

    chunks = load_notes()
    questions = load_questions(args.questions, {chunk.id for chunk in chunks})
    embedder = make_embedder(args.embedder)
    engine = make_engine()
    try:
        with Session(engine) as session:
            stored = {
                row.id: (row.content_hash, row.embed_model)
                for row in session.scalars(select(NoteChunkRow))
            }
            wanted = {chunk.id: (chunk.content_hash, embedder.name) for chunk in chunks}
            if stored != wanted:
                print(
                    "The database does not hold the current notes: run `make notes-sync`.",
                    file=sys.stderr,
                )
                return 1
            results = run_eval(session, embedder, questions)
    except ModelError as exc:
        print(f"{exc}\nIs Ollama running?", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    report = render_report(results, questions, chunks, embedder_name=embedder.name, k=args.k)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(report)
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
