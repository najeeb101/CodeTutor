"""Run a grading worker: take queued submissions from Postgres and grade them in Docker.

Usage:
    python scripts/worker.py           # run until Ctrl+C (finishes the current job first)
    python scripts/worker.py --drain   # grade everything queued, then exit

Start more processes for more throughput: they share the queue safely (docs/worker.md).
Grading always uses the Docker sandbox, because submitted code is untrusted.
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from types import FrameType

from sqlalchemy.exc import OperationalError

from codetutor.db.engine import make_engine
from codetutor.grader import DockerSandbox, SandboxUnavailableError
from codetutor.worker.loop import WorkerStoppedError, run_worker

log = logging.getLogger("worker")


def install_stop_handlers(stop: threading.Event) -> None:
    """First Ctrl+C / SIGTERM: stop after the current job. Second: stop at once."""

    def handle(signum: int, frame: FrameType | None) -> None:
        if stop.is_set():
            raise KeyboardInterrupt
        log.info("stopping after the current job (Ctrl+C again to stop at once)")
        stop.set()

    signal.signal(signal.SIGINT, handle)
    signal.signal(signal.SIGTERM, handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--drain", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        sandbox = DockerSandbox()
    except SandboxUnavailableError as exc:
        log.error("%s", exc)
        return 1
    stop = threading.Event()
    install_stop_handlers(stop)
    engine = make_engine()
    log.info("worker started (%s)", engine.url.render_as_string(hide_password=True))
    try:
        stats = run_worker(engine, sandbox, stop, drain=args.drain)
    except WorkerStoppedError as exc:
        log.error("%s", exc)
        return 2
    except OperationalError as exc:
        log.error("cannot reach Postgres. Run `make db-up`. (%s)", exc.orig)
        return 1
    except KeyboardInterrupt:
        log.warning("stopped at once; a job that was running is retried when its lease ends")
        return 130
    finally:
        engine.dispose()
    log.info(
        "worker stopped: %d done, %d retried, %d failed, %d lost",
        stats.done,
        stats.retry,
        stats.failed,
        stats.lost,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
