"""Ask the tutor for one hint about a code file and show its trace (Week 4, docs/tutor.md §3).

Usage (Ollama running; `make db-sync` and `make notes-sync` done):
    python scripts/ask_tutor.py cs1.loops.fizzbuzz my_fizzbuzz.py
    python scripts/ask_tutor.py cs1.loops.fizzbuzz my_fizzbuzz.py --level 2 --question "why 15?"
    python scripts/ask_tutor.py cs1.loops.fizzbuzz my_fizzbuzz.py --sandbox subprocess --no-save

The code is graded first (in Docker by default, like try_model.py), then the tutor gives a hint.
The hint and its trace are saved in the `hints` table, unless --no-save.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.evals.clients import make_client, make_embedder
from codetutor.grader import DockerSandbox, SandboxUnavailableError, SubprocessSandbox, grade
from codetutor.problems.loader import load_all
from codetutor.tutor.context import LEVELS, HintRequest
from codetutor.tutor.notes import DEFAULT_EMBEDDER
from codetutor.tutor.service import HintResult, TutorConfig, give_hint, save_hint


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("problem_id", help="e.g. cs1.loops.fizzbuzz")
    parser.add_argument("file", type=Path, help="the student's Python file")
    parser.add_argument("--level", type=int, choices=LEVELS, default=1)
    parser.add_argument("--question", default=None, help="the student's question")
    parser.add_argument("--earlier", action="append", default=[], help="a hint already shown")
    parser.add_argument("--model", default=TutorConfig().model)
    parser.add_argument("--sandbox", choices=["docker", "subprocess"], default="docker")
    parser.add_argument("--no-save", action="store_true", help="don't store the hint")
    args = parser.parse_args()

    problem = {problem.id: problem for problem in load_all()}.get(args.problem_id)
    if problem is None:
        print(f"unknown problem {args.problem_id!r}", file=sys.stderr)
        return 1
    code = args.file.read_text(encoding="utf-8")
    try:
        sandbox = DockerSandbox() if args.sandbox == "docker" else SubprocessSandbox()
    except SandboxUnavailableError as exc:
        print(
            f"{exc}\nStart Docker, or use --sandbox subprocess for code you trust.", file=sys.stderr
        )
        return 1
    result = grade(problem, code, reveal_hidden=False, sandbox=sandbox)
    print(f"graded: {result.status.value}, {result.passed}/{result.total} tests passed")
    request = HintRequest(
        problem,
        code,
        args.level,
        question=args.question,
        result=result,
        earlier_hints=tuple(args.earlier),
    )
    engine = make_engine()
    try:
        with Session(engine) as session:
            hint = give_hint(
                request,
                model=make_client(args.model),
                session=session,
                embedder=make_embedder(DEFAULT_EMBEDDER),
                config=TutorConfig(model=args.model),
            )
            _show(hint)
            if not args.no_save:
                row = save_hint(session, request, hint)
                session.commit()
                print(f"saved as hint {row.id}")
    except IntegrityError:
        print(
            f"{problem.id} v{problem.version} is not in the database: run `make db-sync`.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()
    return 0


def _show(hint: HintResult) -> None:
    print(f"\nHINT (level {hint.level}, {hint.source.value}, {hint.latency_ms:.0f} ms):")
    print(f"  {hint.text}\n")
    print(
        f"search: {hint.search_query!r}" + (f" ({hint.search_error})" if hint.search_error else "")
    )
    for item in hint.retrieved:
        print(f"  note: {item.chunk_id} (score {item.score:.3f})")
    for number, attempt in enumerate(hint.attempts, start=1):
        status = attempt.error or ("shown" if attempt.ok else "blocked")
        print(f"attempt {number}: {status}, {attempt.prompt_tokens} prompt tokens")
        for issue in attempt.issues:
            print(f"  - {issue.kind}: {issue.detail}")


if __name__ == "__main__":
    raise SystemExit(main())
