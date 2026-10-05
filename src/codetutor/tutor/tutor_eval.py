"""The offline tutor eval (Week 4 Step 4): does a hint help a student fix a bug? (docs/tutor.md §5)

Situations: the bank's buggy files that pass every visible test and fail only hidden ones
("hidden-only" bugs), comments removed, graded with reveal_hidden=False. The student sees "all
visible tests pass, some hidden ones fail" and doesn't know why: exactly when a hint matters.

A "student" model gets the problem, its buggy code, the test results the UI shows, and maybe a
hint, and must fix the code. `grade()` decides. Six conditions, the same situations in each:
no hint, the teacher's hints 1-3 and the tutor's hints 1-2 (the real pipeline, `give_hint`).

Two phases, both saved to one append-only JSONL file (resumable, like evals/run.py):
1. "hint" records: the tutor's level 1 and level 2 hint for each situation;
2. "answer" records: one per (situation, condition, sample), graded at once.
Model calls go one at a time in a fixed order (seeded answers stay repeatable); grading runs in
a small background pool.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.orm import Session

from codetutor.evals.clients import (
    ChatModel,
    Embedder,
    ModelConfigError,
    ModelError,
    ModelUnavailableError,
)
from codetutor.evals.extract import extract_code
from codetutor.evals.prompt import SYSTEM_PROMPT, build_user_prompt
from codetutor.evals.records import ModelReply
from codetutor.evals.run import git_state, model_details
from codetutor.grader import GRADER_VERSION, Sandbox, grade
from codetutor.grader.models import TestStatus
from codetutor.tutor.context import HintRequest, describe_result
from codetutor.tutor.prompt import TUTOR_PROMPT_VERSION
from codetutor.tutor.safety import Situation
from codetutor.tutor.service import TutorConfig, give_hint

_REPO = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_DIR = _REPO / "lab" / "tutor" / "results"
SCRATCH_DIR = _REPO / "lab" / "tutor" / "scratch"
DEFAULT_REPORT = _REPO / "lab" / "tutor" / "reports" / "tutor_eval.md"

# Bump whenever the student's prompt text changes (a pinned test checks it).
STUDENT_PROMPT_VERSION = "1"
TASK = (
    "### Your task\n"
    "The code above has a bug: some hidden tests fail. Fix it so that every test passes, the "
    "visible and the hidden ones. Reply with the complete corrected function in one ```python "
    "code block."
)
CONDITIONS = ("none", "teacher-1", "tutor-1", "teacher-2", "tutor-2", "teacher-3")
TUTOR_LEVELS = (1, 2)
MAX_FAILURES_IN_A_ROW = 5

# Called after each saved record with (record, records saved in this phase, records expected).
Progress = Callable[[dict[str, Any], int, int], None]


class TutorEvalMismatchError(RuntimeError):
    """A results file was made with other settings; answers can't be mixed."""


class TutorEvalSettings(BaseModel):
    """What makes two runs comparable. Which conditions run now is not part of it: a pilot
    with `none` only can be completed later with the other conditions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    student: str = "ollama/qwen2.5-coder:1.5b-instruct-fp16"
    tutor: str = "ollama/qwen2.5-coder:7b"
    samples: int = 5
    temperature: float = 0.8
    max_tokens: int = 1024
    seed_base: int = 0  # sample i gets seed seed_base + i (Ollama answers repeat exactly)

    def seed_for(self, sample_index: int) -> int:
        return self.seed_base + sample_index


class TutorEvalMeta(BaseModel):
    """Saved next to the results: everything that produced them."""

    model_config = ConfigDict(extra="forbid")

    settings: TutorEvalSettings
    student_prompt_version: str
    tutor_prompt_version: str
    tutor_config: dict[str, JsonValue]
    grader_version: str
    problem_versions: dict[str, int]
    model_details: dict[str, dict[str, JsonValue]]
    git_commit: str | None
    git_dirty: bool | None
    started_at: datetime


@dataclass
class PhaseSummary:
    """What one phase (hints or answers) did in this call."""

    expected: int
    already_done: int
    added: int = 0
    failed_calls: list[str] = field(default_factory=list)
    stop_reason: str | None = None


# --- Situations and prompts ---


def key(situation: Situation) -> str:
    """A situation's id in the results, e.g. "cs1.loops.fizzbuzz/checks_fizz_first"."""
    return f"{situation.problem.id}/{situation.buggy}"


def hidden_only(situations: Iterable[Situation]) -> list[Situation]:
    """The situations where every visible test passes and a hidden one fails (no injections)."""
    picked = []
    for situation in situations:
        tests = situation.result.tests
        visible_ok = all(test.status == TestStatus.PASSED for test in tests if not test.hidden)
        hidden_bad = any(test.status != TestStatus.PASSED for test in tests if test.hidden)
        if not situation.injected and tests and visible_ok and hidden_bad:
            picked.append(situation)
    return picked


def build_student_messages(situation: Situation, hint: str | None) -> list[dict[str, str]]:
    """The student's prompt: the Week 2 problem prompt (student view), the buggy code, the
    results the UI shows (visible details, hidden counts only), maybe a hint, and the task."""
    problem = situation.problem
    parts = [
        build_user_prompt(problem.to_student_view()).rstrip(),
        f"### Your code so far\n```python\n{situation.code.rstrip()}\n```",
        f"### Test results of this code\n{describe_result(problem, situation.result)}",
    ]
    if hint is not None:
        parts.append(f"### A hint from your tutor\n{hint.strip()}")
    parts.append(TASK)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts) + "\n"},
    ]


def tutor_hint_key(situation: Situation, level: int) -> str:
    return f"{key(situation)}#{level}"


def hint_for(situation: Situation, condition: str, tutor_hints: dict[str, str]) -> str | None:
    """The hint text a condition gives (None for "none"). KeyError: the tutor hint is missing."""
    if condition == "none":
        return None
    kind, _, level = condition.partition("-")
    if kind == "teacher":
        return situation.problem.hints[int(level) - 1]
    if kind == "tutor":
        return tutor_hints[tutor_hint_key(situation, int(level))]
    raise ValueError(f"unknown condition {condition!r}")


# --- The results file ---


def results_path(results_dir: Path, student: str) -> Path:
    """lab/tutor/results/tutor-eval-<student model>.jsonl"""
    name = re.sub(r"[^A-Za-z0-9.-]+", "-", student).strip("-")
    return results_dir / f"tutor-eval-{name}.jsonl"


def meta_path_for(path: Path) -> Path:
    return path.with_suffix(".meta.json")


def read_records(path: Path) -> list[dict[str, Any]]:
    """Every record of a results file (none if it doesn't exist)."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def start_or_check_meta(
    settings: TutorEvalSettings,
    tutor_config: TutorConfig,
    situations: Sequence[Situation],
    path: Path,
    *,
    ask_models: bool = True,
) -> TutorEvalMeta:
    """Write the meta file for a new run, or check that a resumed run has the same settings.

    `ask_models=False` skips asking Ollama for the model digests (tests, fake models).
    """
    commit, dirty = git_state()
    details = (
        {name: model_details(name) for name in (settings.student, settings.tutor)}
        if ask_models
        else {}
    )
    current = TutorEvalMeta(
        settings=settings,
        student_prompt_version=STUDENT_PROMPT_VERSION,
        tutor_prompt_version=TUTOR_PROMPT_VERSION,
        tutor_config=asdict(tutor_config),
        grader_version=GRADER_VERSION,
        problem_versions={s.problem.id: s.problem.version for s in situations},
        model_details=details,
        git_commit=commit,
        git_dirty=dirty,
        started_at=datetime.now(UTC),
    )
    meta_path = meta_path_for(path)
    if not meta_path.exists():
        if read_records(path):
            raise TutorEvalMismatchError(f"{path} has records but no {meta_path.name}")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(current.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return current
    stored = TutorEvalMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    names = [
        "settings",
        "student_prompt_version",
        "tutor_prompt_version",
        "tutor_config",
        "grader_version",
        "problem_versions",
    ]
    # Compare digests only when both sides have them (empty = Ollama not asked or not reachable).
    if current.model_details and all(current.model_details.values()) and stored.model_details:
        names.append("model_details")
    changed = [name for name in names if getattr(stored, name) != getattr(current, name)]
    if changed:
        raise TutorEvalMismatchError(
            f"{path.name} was made with a different {', '.join(changed)}: "
            "answers made under different settings can't be compared; use a new results file"
        )
    return stored


# --- Phase 1: the tutor's hints ---


def tutor_hints_in(records: Iterable[dict[str, Any]]) -> dict[str, str]:
    """{"<problem>/<buggy>#<level>": hint text} from the saved hint records."""
    return {f"{r['situation']}#{r['level']}": r["text"] for r in records if r["kind"] == "hint"}


def make_tutor_hints(
    situations: Sequence[Situation],
    tutor: ChatModel,
    path: Path,
    *,
    session: Session | None,
    embedder: Embedder | None,
    config: TutorConfig,
    on_record: Progress | None = None,
) -> PhaseSummary:
    """Ask the tutor for a level 1 and a level 2 hint per situation (level 2 knows level 1),
    through the real pipeline, and save each one. Situations already saved are skipped.

    `give_hint` never raises for a model failure (it falls back to the teacher's hint), so the
    fallbacks are part of what the tutor really shows, and they count.
    """
    done = tutor_hints_in(read_records(path))
    todo = [s for s in situations if tutor_hint_key(s, TUTOR_LEVELS[-1]) not in done]
    summary = PhaseSummary(
        expected=len(situations) * len(TUTOR_LEVELS),
        already_done=(len(situations) - len(todo)) * len(TUTOR_LEVELS),
    )
    for situation in todo:
        earlier: tuple[str, ...] = ()
        for level in TUTOR_LEVELS:
            request = HintRequest(
                situation.problem,
                situation.code,
                level,
                result=situation.result,
                earlier_hints=earlier,
            )
            hint = give_hint(
                request, model=tutor, session=session, embedder=embedder, config=config
            )
            record = {
                "kind": "hint",
                "situation": key(situation),
                "level": level,
                "text": hint.text,
                "source": hint.source.value,
                "attempts": len(hint.attempts),
                "not_shown": sum(1 for attempt in hint.attempts if not attempt.ok),
                "retrieved": [item.chunk_id for item in hint.retrieved],
                "search_error": hint.search_error,
                "latency_ms": round(hint.latency_ms, 1),
            }
            _append(path, record)
            summary.added += 1
            if on_record is not None:
                on_record(record, summary.already_done + summary.added, summary.expected)
            earlier = (*earlier, hint.text)
    return summary


# --- Phase 2: the student's answers ---


def answer_key(situation_key: str, condition: str, sample_index: int) -> str:
    return f"{situation_key}|{condition}|{sample_index}"


def run_student(
    situations: Sequence[Situation],
    conditions: Sequence[str],
    settings: TutorEvalSettings,
    student: ChatModel,
    sandbox: Sandbox,
    path: Path,
    *,
    grade_workers: int = 2,
    on_record: Progress | None = None,
) -> PhaseSummary:
    """Ask the student for every missing (situation, condition, sample), grade each answer and
    save it. Stops after MAX_FAILURES_IN_A_ROW failed calls; a failed call is never graded.

    Raises ModelConfigError / ModelUnavailableError (nothing can work), and ValueError if a tutor
    condition is asked for before its hints exist.
    """
    unknown = [condition for condition in conditions if condition not in CONDITIONS]
    if unknown:
        raise ValueError(f"unknown conditions {unknown}; known: {CONDITIONS}")
    records = read_records(path)
    tutor_hints = tutor_hints_in(records)
    missing = [
        f"{key(situation)} {condition}"
        for situation in situations
        for condition in conditions
        if condition.startswith("tutor-")
        and tutor_hint_key(situation, int(condition[-1])) not in tutor_hints
    ]
    if missing:
        raise ValueError(
            f"no tutor hint for {missing[0]} (and {len(missing) - 1} more): "
            "run make_tutor_hints first"
        )
    done = {
        answer_key(r["situation"], r["condition"], r["sample_index"])
        for r in records
        if r["kind"] == "answer"
    }
    jobs = [
        (situation, condition, index)
        for situation in situations
        for condition in conditions
        for index in range(settings.samples)
    ]
    todo = [job for job in jobs if answer_key(key(job[0]), job[1], job[2]) not in done]
    summary = PhaseSummary(expected=len(jobs), already_done=len(jobs) - len(todo))
    lock = threading.Lock()

    def grade_and_save(
        situation: Situation, condition: str, index: int, hint: str | None, reply: ModelReply
    ) -> None:
        problem = situation.problem
        extraction = extract_code(reply.text, problem.function_name)
        result = grade(problem, extraction.code, reveal_hidden=False, sandbox=sandbox)
        record = {
            "kind": "answer",
            "situation": key(situation),
            "condition": condition,
            "sample_index": index,
            "seed": settings.seed_for(index),
            "hint": hint,
            "reply": reply.text,
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
            "latency_ms": reply.latency_ms,
            "extract_method": extraction.method,
            "code": extraction.code,
            "status": result.status.value,
            "passed": result.passed,
            "total": result.total,
            "reward": result.reward,
        }
        with lock:
            _append(path, record)
            summary.added += 1
            if on_record is not None:
                on_record(record, summary.already_done + summary.added, summary.expected)

    failures_in_a_row = 0
    with ThreadPoolExecutor(max_workers=grade_workers) as pool:
        gradings: list[Future[None]] = []
        for situation, condition, index in todo:
            hint = hint_for(situation, condition, tutor_hints)
            messages = build_student_messages(situation, hint)
            try:
                reply = student.complete(
                    messages,
                    temperature=settings.temperature,
                    max_tokens=settings.max_tokens,
                    seed=settings.seed_for(index),
                )
            except (ModelConfigError, ModelUnavailableError):
                for grading in gradings:
                    grading.result()  # keep what was already answered
                raise
            except ModelError as exc:
                summary.failed_calls.append(f"{key(situation)} {condition} #{index}: {exc}")
                failures_in_a_row += 1
                if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                    summary.stop_reason = f"{failures_in_a_row} failed model calls in a row"
                    break
                continue
            failures_in_a_row = 0
            gradings.append(pool.submit(grade_and_save, situation, condition, index, hint, reply))
        for grading in gradings:
            grading.result()  # re-raise a grading error (a bug of ours, not the model's)
    return summary
