"""Give one hint (Week 4 Step 2, docs/tutor.md §3).

Level 3 is the bottom-out reference hint (no model). Levels 1-2:
search the notes -> prompt -> model -> checks -> one retry -> the level's reference hint.
The checks: the guardrail (Step 0), an empty or too long hint, and a prompt that may have been
cut. Every attempt is kept in the result, so `save_hint` can store the whole trace.

Ollama gives a model a 4,096-token window by default, and our OpenAI-style calls can't change
it. Measured 2026-10-03: a longer prompt is cut to about half the window (2,050 tokens), keeping
the END, so the system message with the rules is lost and the model doesn't know them. So a
prompt must stay under half the window: it is estimated before sending, and a reply that
reports half the window or more is treated as "maybe cut" and never shown.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from codetutor.db.models import HintRow, HintSource, JobStatus
from codetutor.evals.clients import ChatModel, Embedder, ModelError
from codetutor.evals.extract import strip_thinking
from codetutor.tutor.context import HintRequest, search_text
from codetutor.tutor.guardrail import check_hint
from codetutor.tutor.prompt import TUTOR_PROMPT_VERSION, build_messages, retry_message
from codetutor.tutor.rag import Hit, RetrievalError, SearchMethod, search
from codetutor.worker.jobs import clean_text

CONTEXT_WINDOW_TOKENS = 4096  # Ollama's default (its FAQ); see the module docstring
MAX_PROMPT_TOKENS = CONTEXT_WINDOW_TOKENS // 2
# A cautious estimate: English is ~4 characters per token, code ~3. Checked on real prompts.
CHARS_PER_TOKEN = 3


@dataclass(frozen=True)
class TutorConfig:
    """Settings of the tutor; every saved hint stores them."""

    model: str = "ollama/qwen2.5-coder:7b"
    temperature: float = 0.2
    seed: int = 0
    max_tokens: int = 300
    search_method: SearchMethod = "hybrid"
    search_k: int = 3
    max_words: int = 80
    retries: int = 1  # after a blocked hint; failed calls are not retried here (the client does)


@dataclass(frozen=True)
class Issue:
    """Why an attempt was not shown, e.g. ("code_statement", "x = 1") or ("too_long", "95")."""

    kind: str
    detail: str


@dataclass(frozen=True)
class Attempt:
    """One model reply and its checks. `error` is set when the call itself failed."""

    text: str
    issues: tuple[Issue, ...] = ()
    error: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    prompt_chars: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None and not self.issues


@dataclass(frozen=True)
class Retrieved:
    """A note section that went into the prompt."""

    chunk_id: str
    content_hash: str
    score: float


@dataclass(frozen=True)
class HintResult:
    """The hint shown to the student, and how it was made (the trace)."""

    text: str
    source: HintSource
    level: int
    model: str | None
    prompt_version: str | None
    settings: dict[str, Any]
    attempts: tuple[Attempt, ...] = ()
    retrieved: tuple[Retrieved, ...] = ()
    search_query: str | None = None
    search_error: str | None = None
    latency_ms: float = 0.0


def give_hint(
    request: HintRequest,
    *,
    model: ChatModel | None,
    session: Session | None = None,
    embedder: Embedder | None = None,
    config: TutorConfig | None = None,
) -> HintResult:
    """One hint for `request`. Never raises for a model or search failure: it falls back.

    Without `model`, levels 1-2 give the reference hint. Without `session`, there is no note
    search.
    """
    config = config or TutorConfig()
    start = time.perf_counter()
    problem = request.problem
    settings = asdict(config)
    if request.level == 3:
        return HintResult(problem.hints[2], HintSource.REFERENCE, 3, None, None, settings)
    notes, query, search_error = _search(request, session, embedder, config)
    messages = build_messages(request, notes)
    attempts = _attempts(model, messages, request, config) if model is not None else []
    shown = next((attempt for attempt in attempts if attempt.ok), None)
    return HintResult(
        text=shown.text if shown else problem.hints[request.level - 1],
        source=HintSource.MODEL if shown else HintSource.FALLBACK,
        level=request.level,
        model=config.model if model is not None else None,
        prompt_version=TUTOR_PROMPT_VERSION,
        settings=settings,
        attempts=tuple(attempts),
        retrieved=tuple(Retrieved(hit.chunk_id, hit.content_hash, hit.score) for hit in notes),
        search_query=query,
        search_error=search_error,
        latency_ms=(time.perf_counter() - start) * 1000,
    )


def save_hint(
    session: Session,
    request: HintRequest,
    result: HintResult,
    *,
    user_id: int | None = None,
    submission_id: int | None = None,
) -> HintRow:
    """Store a finished hint and its trace (offline runs; the tutor worker fills queued rows
    with `tutor.jobs.save_hint_result`). The caller commits."""
    row = HintRow(
        user_id=user_id,
        problem_id=request.problem.id,
        problem_version=request.problem.version,
        submission_id=submission_id,
        level=result.level,
        question=request.question,
        student_code=request.code,
        job_status=JobStatus.DONE.value,
        finished_at=func.now(),
        **result_columns(result),
    )
    session.add(row)
    session.flush()  # assigns row.id
    return row


def result_columns(result: HintResult) -> dict[str, Any]:
    """The `hints` columns that hold a finished hint and its trace."""
    return {
        "text": clean_text(result.text),
        "source": result.source.value,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "settings": result.settings,
        "search_query": clean_text(result.search_query),
        "retrieved": [asdict(item) for item in result.retrieved],
        "attempts": [asdict(attempt) for attempt in result.attempts],
        "latency_ms": result.latency_ms,
    }


# How a blocked attempt is described to the model in the retry. The guardrail kinds all become
# "it contains code": naming a solution line would tell the model what the solution looks like.
_REASONS = {
    "solution_line": "it contains code",
    "code_block": "it contains code",
    "code_statement": "it contains code",
    "empty": "it was empty",
    "too_long": "it is longer than 3 sentences or 80 words",
}


def _search(
    request: HintRequest, session: Session | None, embedder: Embedder | None, config: TutorConfig
) -> tuple[list[Hit], str | None, str | None]:
    """(note sections, search text, error). A failed search is not fatal: no notes then."""
    if session is None:
        return [], None, "no database session: no note search"
    query = search_text(request)
    try:
        hits = search(
            session, query, method=config.search_method, k=config.search_k, embedder=embedder
        )
    except (RetrievalError, ModelError, ValueError) as exc:
        return [], query, f"{type(exc).__name__}: {exc}"
    return hits, query, None


def _attempts(
    model: ChatModel, messages: list[dict[str, str]], request: HintRequest, config: TutorConfig
) -> list[Attempt]:
    """Ask, and after a blocked hint ask again (up to `config.retries` times)."""
    attempts: list[Attempt] = []
    for _ in range(1 + config.retries):
        attempt = _ask(model, messages, request, config)
        attempts.append(attempt)
        if attempt.ok or attempt.error is not None:
            break  # shown, or a failed call that a retry can't fix
        reasons = sorted({_REASONS.get(issue.kind, issue.kind) for issue in attempt.issues})
        messages = [
            *messages,
            {"role": "assistant", "content": attempt.text},
            {"role": "user", "content": retry_message(reasons)},
        ]
    return attempts


def _ask(
    model: ChatModel, messages: list[dict[str, str]], request: HintRequest, config: TutorConfig
) -> Attempt:
    """One model call and the checks on its reply."""
    prompt_chars = sum(len(message["content"]) for message in messages)
    estimate = math.ceil(prompt_chars / CHARS_PER_TOKEN)
    if estimate >= MAX_PROMPT_TOKENS:
        error = f"prompt too long: about {estimate} tokens, the limit is {MAX_PROMPT_TOKENS}"
        return Attempt("", error=error, prompt_chars=prompt_chars)
    try:
        reply = model.complete(
            messages,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            seed=config.seed,
        )
    except ModelError as exc:
        return Attempt("", error=f"{type(exc).__name__}: {exc}", prompt_chars=prompt_chars)
    text = strip_thinking(reply.text).strip()
    measured = {
        "latency_ms": reply.latency_ms,
        "prompt_tokens": reply.prompt_tokens,
        "completion_tokens": reply.completion_tokens,
        "prompt_chars": prompt_chars,
    }
    if reply.prompt_tokens is not None and reply.prompt_tokens >= MAX_PROMPT_TOKENS:
        error = f"the prompt may have been cut: {reply.prompt_tokens} tokens reported"
        return Attempt(text, error=error, **measured)
    return Attempt(text, issues=_checks(text, request, config), **measured)


def _checks(text: str, request: HintRequest, config: TutorConfig) -> tuple[Issue, ...]:
    if not text:
        return (Issue("empty", ""),)
    issues = [
        Issue(violation.kind, violation.detail)
        for violation in check_hint(text, request.problem, student_code=request.code)
    ]
    words = len(text.split())
    if words > config.max_words:
        issues.append(Issue("too_long", f"{words} words"))
    return tuple(issues)
