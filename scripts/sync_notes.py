"""Copy the course notes into Postgres with their embeddings (Week 4, docs/tutor.md §2).

Usage (Ollama must be running, with the embedding model pulled):
    python scripts/sync_notes.py
    python scripts/sync_notes.py --embedder ollama/nomic-embed-text --root course/notes

Only new or changed sections are embedded, so a second run with no changes is fast.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.evals.clients import ModelError, make_embedder
from codetutor.tutor.notes import DEFAULT_EMBEDDER, NotesError, sync_notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=None, help="notes folder")
    parser.add_argument("--embedder", default=DEFAULT_EMBEDDER, help="embedding model spec")
    args = parser.parse_args()

    embedder = make_embedder(args.embedder)
    engine = make_engine()
    try:
        with Session(engine) as session:
            report = sync_notes(session, embedder, args.root)
            session.commit()
    except NotesError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ModelError as exc:
        model = args.embedder.partition("/")[2]
        print(
            f"{exc}\nIs Ollama running, and is the model pulled? ollama.exe pull {model}",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()
    print(
        f"notes synced with {embedder.name}: {len(report.added)} added, "
        f"{len(report.changed)} changed, {len(report.unchanged)} unchanged, "
        f"{len(report.removed)} removed"
    )
    for label, ids in (
        ("added", report.added),
        ("changed", report.changed),
        ("removed", report.removed),
    ):
        for chunk_id in ids:
            print(f"  {label}: {chunk_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
