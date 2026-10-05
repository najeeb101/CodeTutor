"""Run the tutor worker: take queued hint requests from Postgres and answer them.

Usage:
    python scripts/tutor_worker.py                 # run until Ctrl+C (finishes the current hint)
    python scripts/tutor_worker.py --drain         # answer everything queued, then exit
    python scripts/tutor_worker.py --model ollama/qwen2.5-coder:1.5b-instruct-fp16

It loads the model and the embedder at start and keeps them loaded while it runs (Ollama
unloads them by itself 10 minutes after it stops). It stops at once if the model can't be
reached: running without it would give only the teacher's hints, silently (docs/tutor.md §4).
"""

from __future__ import annotations

import argparse
import logging
import threading
import time

from sqlalchemy.exc import OperationalError

from codetutor.db.engine import make_engine
from codetutor.evals.clients import ModelError, make_client, make_embedder
from codetutor.tutor.loop import Tutor, run_tutor_worker
from codetutor.tutor.notes import DEFAULT_EMBEDDER
from codetutor.tutor.service import TutorConfig
from codetutor.worker.loop import WorkerStoppedError
from worker import install_stop_handlers  # scripts/worker.py, the same folder

log = logging.getLogger("tutor")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drain", action="store_true", help="exit when the queue is empty")
    parser.add_argument("--model", default=TutorConfig().model, help="an ollama/<model> spec")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.model.startswith("ollama/"):
        log.error("the tutor worker needs a local model: --model ollama/<model>")
        return 1
    model = make_client(args.model)
    embedder = make_embedder(DEFAULT_EMBEDDER)

    def keep_loaded() -> None:
        model.keep_loaded()
        embedder.keep_loaded()

    start = time.perf_counter()
    try:
        keep_loaded()  # loads both now, so the first student doesn't wait for it
    except ModelError as exc:
        log.error("%s\nIs Ollama running, with the model pulled? (docs/tutor.md §4)", exc)
        return 1
    log.info("%s and %s loaded in %.1f s", model.name, embedder.name, time.perf_counter() - start)

    stop = threading.Event()
    install_stop_handlers(stop)
    engine = make_engine()
    tutor = Tutor(model, embedder, TutorConfig(model=args.model))
    log.info("tutor worker started (%s)", engine.url.render_as_string(hide_password=True))
    try:
        stats = run_tutor_worker(engine, tutor, stop, drain=args.drain, keep_loaded=keep_loaded)
    except WorkerStoppedError as exc:
        log.error("%s", exc)
        return 2
    except OperationalError as exc:
        log.error("cannot reach Postgres. Run `make db-up`. (%s)", exc.orig)
        return 1
    except KeyboardInterrupt:
        log.warning("stopped at once; a hint that was running is retried when its lease ends")
        return 130
    finally:
        engine.dispose()
    log.info(
        "tutor worker stopped: %d done, %d retried, %d failed, %d lost",
        stats.done,
        stats.retry,
        stats.failed,
        stats.lost,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
