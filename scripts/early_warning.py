"""Early warning: who may struggle later? (Week 8 Step 3a)

Usage:
    python scripts/early_warning.py report        # lab/early/reports/early_warning.md
    python scripts/early_warning.py show --dev    # the model's top students in the dev database
    python scripts/early_warning.py export-model  # write the model file the API uses

`report` reads the two graded simulated classes (`make sim`, `SIM_SEED=1 make sim`), fits the
model on seed 0 and scores both. It never writes to a database and never reads the cohort
files' labels. `show` scores the dev database with the committed model file (made by `export-model`,
which fits on the simulated class seed 0). `report` refuses to run if that file no longer
matches a fresh fit.
See docs/early-warning.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from codetutor.db.admin import database_name
from codetutor.db.engine import make_engine
from codetutor.early.evaluate import (
    MAIN_CUTOFF,
    TOP_K,
    fit_for,
    score_class,
    stoppers,
)
from codetutor.early.features import course_start, features_at
from codetutor.early.logistic import LogisticModel, predict
from codetutor.early.report import EarlyClass, render_report
from codetutor.early.served import (
    EARLY_VERSION,
    MODEL_FILE,
    ServedModel,
    load_served_model,
    read_model,
    save_model,
)
from codetutor.evals.report import fixed
from codetutor.integrity.signals import SubmissionInfo
from codetutor.integrity.store import load_submissions
from codetutor.settings import database_url, sim_database_url

REPO = Path(__file__).resolve().parents[1]
REPORT = REPO / "lab" / "early" / "reports" / "early_warning.md"
TRAIN_SEED = 0
SEEDS = (0, 1)
CUTOFFS = (1, 2, 3, 4)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("report", help=f"write {REPORT.relative_to(REPO)}")
    show = commands.add_parser("show", help="the top students of one database")
    show.add_argument("--dev", action="store_true", required=True)
    commands.add_parser("export-model", help=f"write {MODEL_FILE.name}")
    args = parser.parse_args()
    try:
        if args.command == "report":
            return _report()
        return _export() if args.command == "export-model" else _show()
    except OperationalError as exc:
        print(
            f"can't reach the database: run `make db-up` (and `make sim`, "
            f"`SIM_SEED=1 make sim`).\n{exc.orig}",
            file=sys.stderr,
        )
        return 1


def _load(url: str) -> list[SubmissionInfo]:
    engine = make_engine(url)
    try:
        with Session(engine) as session:
            return load_submissions(session)
    finally:
        engine.dispose()


def _sim_url(seed: int) -> str:
    url = sim_database_url(seed)
    if "sim" not in database_name(url):
        raise SystemExit(f"refusing: {database_name(url)!r} is not a sim database")
    return url


def _report() -> int:
    data = {seed: _load(_sim_url(seed)) for seed in SEEDS}
    starts = {seed: course_start(rows) for seed, rows in data.items()}
    models = {c: fit_for(data[TRAIN_SEED], c, starts[TRAIN_SEED]) for c in CUTOFFS}
    _check_committed_model(models[MAIN_CUTOFF])
    classes = []
    for seed in SEEDS:
        experiments = {c: score_class(models[c], data[seed], c, starts[seed]) for c in CUTOFFS}
        stopped = stoppers(data[seed], starts[seed])
        flagged = experiments[MAIN_CUTOFF].flagged
        classes.append(
            EarlyClass(
                seed=seed,
                database=database_name(_sim_url(seed)),
                submissions=len(data[seed]),
                students=len({s.student for s in data[seed]}),
                experiments=experiments,
                stopped=len(stopped),
                stopped_flagged=len(stopped & set(flagged)),
            )
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(classes, models, TRAIN_SEED), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


def _fitted_model() -> ServedModel:
    train = _load(_sim_url(TRAIN_SEED))
    model = fit_for(train, MAIN_CUTOFF, course_start(train))
    return ServedModel(model, MAIN_CUTOFF, f"simulated class seed {TRAIN_SEED}", EARLY_VERSION)


def _export() -> int:
    save_model(MODEL_FILE, _fitted_model())
    print(f"wrote {MODEL_FILE.relative_to(REPO)}")
    return 0


def _check_committed_model(fresh: LogisticModel) -> None:
    """The file the API serves must be the model this report measures."""
    try:
        saved = read_model(MODEL_FILE).model
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"{exc}\nrun `uv run python scripts/early_warning.py export-model`"
        ) from exc
    pairs = [
        (saved.weights, fresh.weights),
        (saved.means, fresh.means),
        (saved.spreads, fresh.spreads),
        ([saved.bias], [fresh.bias]),
    ]
    if any(abs(a - b) > 1e-9 for x, y in pairs for a, b in zip(x, y, strict=True)):
        raise SystemExit(
            f"{MODEL_FILE.name} differs from a fresh fit on the simulated class: the report "
            "would not describe the model the API serves. If the change is intended, run "
            "`uv run python scripts/early_warning.py export-model` and commit the file."
        )


def _show() -> int:
    served = load_served_model()
    model = served.model
    rows = _load(database_url())
    if not rows:
        print("no submissions yet")
        return 0
    start = course_start(rows)
    scores = {
        name: predict(model, vector)
        for name, vector in features_at(rows, MAIN_CUTOFF, start).items()
    }
    print(
        f"{database_name(database_url())}: {len(scores)} students with a submission in the first "
        f"{MAIN_CUTOFF} weeks (model fitted on the simulated class)."
    )
    print(f"highest risk scores, top {TOP_K} (a reason to check in, never a verdict):")
    for name, score in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_K]:
        print(f"  {fixed(score, 2):>5}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
