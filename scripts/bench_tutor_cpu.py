"""Time the tutor on a CPU, model by model, and apply the size rule (Deploy Step 4).

Usage (Ollama running, the notes synced: `make notes-sync`):
    python scripts/bench_tutor_cpu.py --model ollama/qwen2.5-coder:1.5b \
        --model ollama/qwen2.5-coder:3b --hints 12

Asks for a level 1 hint in `--hints` buggy-code situations (spread over the whole bank, the same
ones as the Week 4 safety run) with each model, through the real `give_hint` pipeline, then prints
a table and which model the rule picks (docs/tutor.md §6). Models are listed smallest first.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

from sqlalchemy.orm import Session

from codetutor.db.engine import make_engine
from codetutor.evals.clients import make_client, make_embedder
from codetutor.grader import SubprocessSandbox
from codetutor.problems.loader import load_all
from codetutor.tutor.context import HintRequest
from codetutor.tutor.cpu_bench import (
    MAX_MEDIAN_S,
    MAX_REFERENCE_SHARE,
    choose_model,
    evenly_spaced,
    record_from_hint,
    render_table,
    summarize,
)
from codetutor.tutor.notes import DEFAULT_EMBEDDER
from codetutor.tutor.safety import build_situations
from codetutor.tutor.service import TutorConfig, give_hint


def loaded_gb(base: str) -> float | None:
    """The size in GB of what Ollama has loaded right now (/api/ps), or None."""
    try:
        with urllib.request.urlopen(f"{base}/api/ps", timeout=5) as answer:
            models = json.load(answer).get("models", [])
    except (OSError, ValueError):
        return None
    return sum(m.get("size", 0) for m in models) / 1e9 if models else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", action="append", required=True, help="smallest first")
    parser.add_argument("--hints", type=int, default=12, help="situations per model")
    args = parser.parse_args()

    problems = load_all()
    situations = [
        s for s in build_situations(problems, sandbox=SubprocessSandbox()) if not s.injected
    ]
    chosen = evenly_spaced(situations, args.hints)
    print(f"{len(chosen)} situations from {len(situations)}; one level 1 hint each, per model")

    embedder = make_embedder(DEFAULT_EMBEDDER)
    engine = make_engine()
    rows = []
    try:
        for spec in args.model:
            client = make_client(spec)
            client.keep_loaded()  # the first student never waits for the model to load
            embedder.keep_loaded()
            records = []
            started = time.perf_counter()
            with Session(engine) as session:
                for number, s in enumerate(chosen, start=1):
                    request = HintRequest(s.problem, s.code, 1, result=s.result)
                    hint = give_hint(
                        request,
                        model=client,
                        session=session,
                        embedder=embedder,
                        config=TutorConfig(model=spec),
                    )
                    records.append(record_from_hint(hint))
                    print(
                        f"[{spec}] {number:2} {s.problem.id}: {hint.source}, "
                        f"{hint.latency_ms / 1000:.1f} s",
                        flush=True,
                    )
            gb = loaded_gb(client.base_url.removesuffix("/v1"))
            rows.append(summarize(spec, records))
            print(
                f"{spec}: {time.perf_counter() - started:.0f} s in total, {gb:.1f} GB loaded"
                if gb
                else f"{spec}: done"
            )
    finally:
        engine.dispose()

    print()
    print(render_table(rows))
    pick = choose_model(rows, order=args.model)
    passed = any(
        r.median_s <= MAX_MEDIAN_S and r.reference_share <= MAX_REFERENCE_SHARE for r in rows
    )
    print(
        f"\nRule: the largest model with median <= {MAX_MEDIAN_S:.0f} s and teacher's hint shown "
        f"<= {MAX_REFERENCE_SHARE:.0%}."
    )
    print(f"Verdict: {pick}" + ("" if passed else "  (no model passed: the smallest is used)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
