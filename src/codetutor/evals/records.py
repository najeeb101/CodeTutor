"""Eval results as data: one sample = one EvalRecord = one line of JSON (JSONL).

A record keeps everything needed to trust and redo a number later: the raw reply (so code can be
re-extracted and re-graded without calling the model again), the graded code and how it was
found, the full GradeResult (with the grader version), and the model, temperature and prompt
version.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from codetutor.evals.extract import ExtractMethod
from codetutor.grader import GradeResult, GradeStatus

_STRICT = ConfigDict(extra="forbid", frozen=True)


class EvalRecordError(ValueError):
    """A results file has a line that is not a valid EvalRecord."""


class ModelReply(BaseModel):
    """What one model call returns. Fake models fill in only `text`."""

    model_config = _STRICT

    text: str
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # Can be more than prompt + completion: Gemini counts its hidden "thinking" tokens only here.
    total_tokens: int | None = None
    # Why the model stopped: "stop" (finished) or "length" (max_tokens cut the reply off).
    finish_reason: str | None = None


class EvalRecord(BaseModel):
    """One graded sample: one model, one problem, one attempt."""

    model_config = _STRICT

    run_id: str | None = None  # None for one-off checks (try_model.py)
    model: str  # e.g. "ollama/qwen2.5-coder:1.5b" or "fake/oracle"
    temperature: float
    max_tokens: int | None = None
    seed: int | None = None  # None: no seed was sent (Gemini rejects seeds)
    prompt_version: str
    problem_id: str
    problem_version: int
    sample_index: int  # 0 .. n-1 for this model and problem
    reply: ModelReply
    code: str  # what was graded
    extract_method: ExtractMethod
    result: GradeResult  # includes grader_version
    created_at: datetime  # UTC

    @property
    def passed(self) -> bool:
        """True if every test passed. pass@k counts only these samples as correct."""
        return self.result.status == GradeStatus.ACCEPTED


def append_records(path: Path, records: Iterable[EvalRecord]) -> None:
    """Add records to the end of a JSONL file (created if missing), one line each."""
    with Path(path).open("a", encoding="utf-8") as file:
        for record in records:
            file.write(record.model_dump_json() + "\n")


def read_records(path: Path) -> list[EvalRecord]:
    """Read every record from a JSONL file. Raises EvalRecordError naming the bad line."""
    records: list[EvalRecord] = []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(EvalRecord.model_validate_json(line))
        except ValidationError as exc:
            raise EvalRecordError(f"{path}, line {number}: not a valid EvalRecord\n{exc}") from exc
    return records
