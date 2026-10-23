"""The run harness: one model, many problems, n answers each; every answer graded and saved.

One run = one config = one results file (JSONL), plus a meta file next to it.

- **Append-only and resumable.** Each answer is saved as soon as it is graded, so a crash or a
  used-up quota loses almost nothing. Running the same config again only asks for the samples
  that are not in the file yet.
- **No mixing.** The meta file records what produced the answers (config, prompt and grader
  versions, problem versions, git commit, Ollama model digest). A run with different settings
  refuses to add to the same file (RunMismatchError).
- **Model calls one at a time, in a fixed order.** Two requests at once may be batched by Ollama,
  which can change seeded answers. Grading (Docker, ~1 s) runs in the background meanwhile.
- **A failed model call is never graded.** It is counted, and a rerun fills the gap.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from codetutor.evals.clients import (
    OLLAMA_BASE_URL,
    OLLAMA_URL_ENV,
    ModelConfigError,
    ModelError,
    ModelUnavailableError,
    QuotaExhaustedError,
    make_client,
)
from codetutor.evals.fake_models import FAKE_MODELS
from codetutor.evals.prompt import PROMPT_VERSION, build_messages
from codetutor.evals.records import EvalRecord, ModelReply, append_records, read_records
from codetutor.evals.score import score_reply
from codetutor.grader import GRADER_VERSION, DockerSandbox, Sandbox, SubprocessSandbox
from codetutor.problems import Problem

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "lab" / "evals" / "results"  # official runs (committed)
SCRATCH_DIR = REPO_ROOT / "lab" / "evals" / "scratch"  # test and smoke runs (gitignored)
MAX_FAILURES_IN_A_ROW = 5
# model id -> details of the loaded Hugging Face generator. Module-level on purpose: the
# harness builds the responder first and the meta file afterwards, and this is how the meta
# learns what was loaded (one entry per model per process).
_HF_DETAILS: dict[str, dict[str, JsonValue]] = {}

_STRICT = ConfigDict(extra="forbid", frozen=True)

# (problem, chat messages, seed) -> reply. Real models only use the messages; fake ones cheat.
Responder = Callable[[Problem, list[dict[str, str]], int | None], ModelReply]
# Called after each saved answer with (record, answers saved so far, answers expected).
ProgressCallback = Callable[[EvalRecord, int, int], None]


class RunMismatchError(RuntimeError):
    """The results file was made with different settings, so new answers can't be added to it."""


class RunConfig(BaseModel):
    """Everything that defines a run. Loaded from lab/evals/configs/<name>.yaml."""

    model_config = _STRICT

    run_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")]  # also the file name
    model: str  # "ollama/<model>", "gemini/<model>" or "fake/<name>"
    samples: Annotated[int, Field(ge=1)]  # answers per problem (n in pass@k)
    temperature: Annotated[float, Field(ge=0)]
    max_tokens: Annotated[int, Field(ge=1)]
    seed_base: int | None = None  # sample i gets seed seed_base + i; None = send no seed
    rpm: Annotated[float, Field(gt=0)] | None = None  # max requests per minute
    extra_body: dict[str, JsonValue] = Field(default_factory=dict)  # extra request fields
    problems: list[str] | None = None  # problem ids; None = the whole bank
    sandbox: Literal["docker", "subprocess"] = "docker"
    grade_workers: Annotated[int, Field(ge=1)] = 2
    adapter: str | None = None  # hf/ models only: a trained LoRA adapter folder (Week 6 Step 5)

    def seed_for(self, sample_index: int) -> int | None:
        """The seed for one sample, or None when the run sends no seeds."""
        return None if self.seed_base is None else self.seed_base + sample_index


class RunMeta(BaseModel):
    """What produced a results file. Saved as <run_id>.meta.json when the run starts."""

    model_config = _STRICT

    config: RunConfig
    prompt_version: str
    grader_version: str
    problem_versions: dict[str, int]
    model_details: dict[str, JsonValue]  # e.g. Ollama's digest and precision; {} if unknown
    git_commit: str | None
    git_dirty: bool | None  # True: committed files had uncommitted changes at the start
    started_at: datetime


@dataclass
class RunSummary:
    """What one call of run_eval did."""

    expected: int  # problems x samples
    already_done: int  # answers found in the results file at the start
    added: int = 0  # answers graded and saved by this call
    failed_calls: list[str] = field(default_factory=list)  # "problem_id #i: error", not graded
    stop_reason: str | None = None  # None: every missing sample was asked

    @property
    def missing(self) -> int:
        """Answers still not in the file. Running the same config again asks for these."""
        return self.expected - self.already_done - self.added


def load_run_config(path: Path) -> RunConfig:
    """Read and check a run config YAML file."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return RunConfig.model_validate(data)


def meta_path_for(results_path: Path) -> Path:
    """lab/evals/results/x.jsonl -> lab/evals/results/x.meta.json"""
    return Path(results_path).with_suffix(".meta.json")


def make_responder(config: RunConfig) -> Responder:
    """A fake model (fake/...) or a real client, wrapped as a Responder."""
    if config.model.startswith("fake/"):
        fake = FAKE_MODELS.get(config.model)
        if fake is None:
            raise ValueError(f"unknown fake model {config.model!r}: use one of {list(FAKE_MODELS)}")

        def answer_fake(
            problem: Problem, messages: list[dict[str, str]], seed: int | None
        ) -> ModelReply:
            return fake(problem)

        return answer_fake

    if config.model.startswith("hf/"):  # a Hugging Face model on the local GPU (Week 6)
        from codetutor.rl.hf import BatchedResponder, HFGenerator

        generator = HFGenerator(
            config.model.removeprefix("hf/"),
            config.temperature,
            config.max_tokens,
            adapter=config.adapter,
        )
        batched = BatchedResponder(
            lambda messages, n, offset: generator(messages, n, offset),
            config.samples,
            seed_base=config.seed_base or 0,
        )
        _HF_DETAILS[config.model] = generator.details()
        return batched

    client = make_client(config.model, rpm=config.rpm, extra_body=config.extra_body)

    def answer(problem: Problem, messages: list[dict[str, str]], seed: int | None) -> ModelReply:
        return client.complete(
            messages, temperature=config.temperature, max_tokens=config.max_tokens, seed=seed
        )

    return answer


def make_sandbox(config: RunConfig) -> Sandbox:
    """Docker for model code (untrusted); subprocess only for tests and trusted code."""
    return DockerSandbox() if config.sandbox == "docker" else SubprocessSandbox()


def git_state() -> tuple[str | None, bool | None]:
    """The current commit and whether there are uncommitted changes (None if git fails)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            # Untracked files (e.g. another run's new results file) are not code changes.
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None, None
    return commit, bool(status.strip())


def model_details(model: str) -> dict[str, JsonValue]:
    """The exact model identity, where the provider tells us (Ollama: digest and precision)."""
    provider, _, name = model.partition("/")
    if provider == "hf":  # filled in by make_responder when the model was loaded
        return dict(_HF_DETAILS.get(model, {}))
    if provider != "ollama":
        return {}
    base_url = (os.environ.get(OLLAMA_URL_ENV) or OLLAMA_BASE_URL).removesuffix("/v1")
    try:
        with urllib.request.urlopen(f"{base_url}/api/tags", timeout=10) as response:
            models = json.load(response)["models"]
    except (OSError, ValueError, KeyError):
        return {}  # Ollama not reachable: the run itself will report that clearly
    for entry in models:
        if entry.get("name") == name:
            details = entry.get("details", {})
            return {
                "digest": entry.get("digest"),
                "quantization": details.get("quantization_level"),
                "parameter_size": details.get("parameter_size"),
            }
    return {}


def _start_or_check_meta(config: RunConfig, problems: list[Problem], results_path: Path) -> RunMeta:
    """Write the meta file for a new run, or check that a resumed run has the same settings."""
    commit, dirty = git_state()
    current = RunMeta(
        config=config,
        prompt_version=PROMPT_VERSION,
        grader_version=GRADER_VERSION,
        problem_versions={problem.id: problem.version for problem in problems},
        model_details=model_details(config.model),
        git_commit=commit,
        git_dirty=dirty,
        started_at=datetime.now(UTC),
    )
    meta_path = meta_path_for(results_path)
    if not meta_path.exists():
        if results_path.exists() and results_path.stat().st_size > 0:
            raise RunMismatchError(f"{results_path} has answers but no {meta_path.name}")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(current.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return current

    stored = RunMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    names = ["config", "prompt_version", "grader_version", "problem_versions"]
    if current.model_details:  # empty = couldn't ask the provider now; don't call that a change
        names.append("model_details")
    changed = [name for name in names if getattr(stored, name) != getattr(current, name)]
    if changed:
        raise RunMismatchError(
            f"{results_path.name} was made with a different {', '.join(changed)}. "
            "Answers made under different settings can't be compared: use a new run_id."
        )
    return stored


def _done_samples(results_path: Path) -> set[tuple[str, int]]:
    """(problem_id, sample_index) of every answer already saved."""
    if not results_path.exists():
        return set()
    return {(record.problem_id, record.sample_index) for record in read_records(results_path)}


def run_eval(
    config: RunConfig,
    problems: list[Problem],
    responder: Responder,
    sandbox: Sandbox,
    results_path: Path,
    *,
    on_record: ProgressCallback | None = None,
) -> RunSummary:
    """Ask for every missing (problem, sample), grade each answer, and append it to the file.

    Stops early on a used-up quota or after MAX_FAILURES_IN_A_ROW failed calls (see the
    summary). Raises RunMismatchError, ModelConfigError or ModelUnavailableError.
    """
    results_path = Path(results_path)
    _start_or_check_meta(config, problems, results_path)
    done = _done_samples(results_path)
    todo = [
        (problem, index)
        for problem in problems
        for index in range(config.samples)
        if (problem.id, index) not in done
    ]
    expected = len(problems) * config.samples
    summary = RunSummary(expected=expected, already_done=expected - len(todo))
    lock = threading.Lock()  # one writer at a time for the file and the summary

    def grade_and_save(problem: Problem, index: int, reply: ModelReply, seed: int | None) -> None:
        record = score_reply(
            problem,
            reply,
            model=config.model,
            temperature=config.temperature,
            sample_index=index,
            run_id=config.run_id,
            seed=seed,
            max_tokens=config.max_tokens,
            reveal_hidden=True,
            sandbox=sandbox,
        )
        with lock:
            append_records(results_path, [record])
            summary.added += 1
            if on_record is not None:
                on_record(record, summary.already_done + summary.added, expected)

    fatal: ModelError | None = None
    failures_in_a_row = 0
    with ThreadPoolExecutor(max_workers=config.grade_workers) as pool:
        gradings: list[Future[None]] = []
        for problem, index in todo:
            seed = config.seed_for(index)
            try:
                reply = responder(problem, build_messages(problem.to_student_view()), seed)
            except QuotaExhaustedError as exc:
                summary.stop_reason = f"daily quota used up ({exc})"
                break
            except (ModelConfigError, ModelUnavailableError) as exc:
                summary.stop_reason = str(exc)
                fatal = exc
                break
            except ModelError as exc:
                summary.failed_calls.append(f"{problem.id} #{index}: {exc}")
                failures_in_a_row += 1
                if failures_in_a_row >= MAX_FAILURES_IN_A_ROW:
                    summary.stop_reason = f"{failures_in_a_row} failed model calls in a row"
                    break
                continue
            failures_in_a_row = 0
            gradings.append(pool.submit(grade_and_save, problem, index, reply, seed))
        for grading in gradings:
            grading.result()  # re-raise any grading error (that would be a bug, not the model)
    if fatal is not None:
        raise fatal
    return summary
