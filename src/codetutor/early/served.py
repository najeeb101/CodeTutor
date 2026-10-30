"""The early-warning model as the instructor API uses it (Week 8 Step 3b).

The API does not fit anything: it loads a small file (`model_week3.json`) that
`scripts/early_warning.py export-model` wrote after fitting on the simulated class seed 0, and
scores the live class with it. The file is committed and versioned, and `make early` refuses
to run if it no longer matches a fresh fit, so the number a teacher sees can't drift quietly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from codetutor.early.features import FEATURE_NAMES, course_start, features_at, week_of
from codetutor.early.logistic import LogisticModel, model_from_json, model_to_json, predict
from codetutor.integrity.signals import SubmissionInfo

EARLY_VERSION = "1"
MODEL_FILE = Path(__file__).with_name("model_week3.json")


@dataclass(frozen=True)
class ServedModel:
    """A fitted model plus what it was made for."""

    model: LogisticModel
    cutoff: int  # the week the model looks at (it reads weeks 1..cutoff)
    fitted_on: str  # e.g. "simulated class seed 0"
    version: str


def save_model(path: Path, served: ServedModel) -> None:
    """Write the model file (stable key order, so the file diffs cleanly)."""
    payload = {
        "version": served.version,
        "cutoff": served.cutoff,
        "fitted_on": served.fitted_on,
        "feature_names": list(FEATURE_NAMES),
        **model_to_json(served.model),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_model(path: Path) -> ServedModel:
    """Read a model file. Refuses a file made for other inputs (names or order differ)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError(
            f"{path.name} was made for inputs {data.get('feature_names')}, but the code uses "
            f"{list(FEATURE_NAMES)}: run `uv run python scripts/early_warning.py export-model`"
        )
    return ServedModel(
        model=model_from_json(data),
        cutoff=int(data["cutoff"]),
        fitted_on=str(data["fitted_on"]),
        version=str(data["version"]),
    )


@cache
def load_served_model() -> ServedModel:
    """The committed model, read once per process."""
    return read_model(MODEL_FILE)


def risk_scores(
    submissions: Sequence[SubmissionInfo], served: ServedModel | None = None
) -> dict[str, float] | None:
    """Each student's chance of struggling later, from weeks 1..cutoff only.

    None while the class has no submission in week `cutoff` or later: before that the model
    would score a part of the weeks it was built for. A student without a submission in those
    weeks has no entry.
    """
    served = served or load_served_model()
    if not submissions:
        return None
    start = course_start(submissions)
    if max(week_of(s.created_at, start) for s in submissions) < served.cutoff:
        return None
    vectors = features_at(submissions, served.cutoff, start)
    return {name: predict(served.model, vector) for name, vector in vectors.items()}
