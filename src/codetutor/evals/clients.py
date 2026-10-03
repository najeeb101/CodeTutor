"""Talk to models over HTTP: chat models (Ollama, Gemini) and embedding models (Ollama).

Both providers accept the OpenAI "chat completions" format, so one client covers both; only the
base URL and the API key differ. Ollama also serves OpenAI-style "/embeddings" (Week 4: the
tutor's search). Standard library only (urllib + json): no SDK and no LiteLLM (decision
2026-10-01). Used by the evals (Week 2) and the tutor (Week 4).

Every failure is sorted into one kind:
- transient (429 per minute, 5xx, timeout, dropped connection, or an HTTP 200 reply whose
  finish_reason is "error" because the provider failed mid-answer): wait longer each time, retry;
- daily quota used up (a 429 that names a per-day quota): QuotaExhaustedError, stop the run;
- wrong settings (400/401/403/404): ModelConfigError at once, because retrying can't help;
- nothing listening (connection refused, unknown host): ModelUnavailableError at once.

A failed call must never be graded as a wrong answer: an infrastructure failure is not a model
failure, and counting it would push pass@k down.
"""

from __future__ import annotations

import http.client
import json
import math
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from codetutor.evals.records import ModelReply

OLLAMA_BASE_URL = "http://localhost:11434/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
OLLAMA_URL_ENV = "OLLAMA_BASE_URL"
GEMINI_KEY_ENV = "GEMINI_API_KEY"

DEFAULT_TIMEOUT_S = 120.0  # the first Ollama call also loads the model into the GPU
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_S = 2.0  # waits of about 2, 4, 8, 16 s (each randomly 50-100%: jitter)
MAX_WAIT_S = 60.0  # never wait longer than this between two attempts
TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})
CONFIG_STATUSES = frozenset({400, 401, 403, 404})
# HTTP 200, but the provider says it failed (OpenRouter sends "error"): a failed call, not a reply.
FAILED_FINISH_REASONS = frozenset({"error"})
MAX_ERROR_BODY_BYTES = 64_000  # read this much of an error reply (quota details can be long)
MAX_MESSAGE_CHARS = 500  # but quote only this much of it in our error message

# Gemini names the quota that was hit, e.g. "GenerateRequestsPerDayPerProjectPerModel-FreeTier".
_DAILY_QUOTA = re.compile(r"per ?day", re.IGNORECASE)
# Gemini says how long to wait in the body: "retryDelay": "33s".
_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')

T = TypeVar("T")  # what a reply is parsed into

EMBED_BATCH_SIZE = 32  # texts per /embeddings request


@dataclass(frozen=True)
class EmbedderInfo:
    """What we must know about an embedding model: its vector size and its task prefixes."""

    dimensions: int
    document_prefix: str = ""  # put before every stored text
    query_prefix: str = ""  # put before every search question


# nomic-embed-text v1.5 gives 768 numbers, and its model card says every text *must* start with
# a task prefix (checked on Hugging Face, 2026-10-02).
KNOWN_EMBEDDERS = {
    "nomic-embed-text": EmbedderInfo(768, "search_document: ", "search_query: "),
}


class ModelError(RuntimeError):
    """A model call failed (after any retries)."""


class ModelConfigError(ModelError):
    """The request itself is wrong (key, model name, parameters): retrying can't help."""


class ModelUnavailableError(ModelError):
    """Nothing answers at the base URL (server not running, wrong address, no network)."""


class QuotaExhaustedError(ModelError):
    """The provider's daily quota is used up: stop now and resume later."""


class _Transient(Exception):
    """A failure worth retrying, with the wait the server asked for (if it said)."""

    def __init__(self, message: str, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ChatModel(Protocol):
    """Anything that answers chat messages. ChatClient is the real one."""

    name: str

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
    ) -> ModelReply: ...


class Embedder(Protocol):
    """Anything that turns texts into vectors. EmbeddingClient is the real one."""

    name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _retry_after_s(header: str | None, body: str) -> float | None:
    """The wait the server asked for: the Retry-After header, else Gemini's retryDelay."""
    if header:
        try:
            return float(header)
        except ValueError:
            pass  # an HTTP date instead of seconds: fall back to our own backoff
    match = _RETRY_DELAY.search(body)
    return float(match[1]) if match else None


class _HttpClient:
    """What our model clients share: one POST, with retries, a throttle and error sorting.

    Safe to share between threads: the only shared state is the throttle, which uses a lock.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_s: float = DEFAULT_BACKOFF_S,
        min_interval_s: float = 0.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._next_start = 0.0  # time.monotonic() before which no request may start

    def __repr__(self) -> str:
        # Never show the key, so it can't end up in logs or tracebacks.
        kind = type(self).__name__
        return f"{kind}(name={self.name!r}, base_url={self.base_url!r}, model={self.model!r})"

    def _call(self, path: str, body: dict[str, Any], parse: Callable[[bytes, float], T]) -> T:
        """POST `body` to `path`, then `parse(raw reply, latency_ms)`; retry transient failures.

        Raises QuotaExhaustedError, ModelConfigError, ModelUnavailableError or ModelError.
        """
        attempt = 0
        while True:
            try:
                raw, latency_ms = self._post_once(path, body)
                return parse(raw, latency_ms)
            except _Transient as exc:
                if attempt == self.max_retries:
                    tries = attempt + 1
                    raise ModelError(f"{self.name}: gave up after {tries} tries: {exc}") from exc
                time.sleep(self._wait_s(attempt, exc.retry_after_s))
                attempt += 1

    def _wait_s(self, attempt: int, retry_after_s: float | None) -> float:
        """How long to wait before the next try: what the server asked, else backoff + jitter."""
        if retry_after_s is not None:
            return min(retry_after_s, MAX_WAIT_S)
        # Jitter (a random 50-100% of the wait) stops many clients from retrying in lockstep.
        exponential = self.backoff_s * 2**attempt
        return min(exponential * random.uniform(0.5, 1.0), MAX_WAIT_S)

    def _wait_for_turn(self) -> None:
        """Keep at least min_interval_s between request starts (for per-minute rate limits)."""
        if self.min_interval_s <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_start)
            self._next_start = start + self.min_interval_s
        time.sleep(start - now)  # sleep outside the lock, so other threads can book a slot

    def _post_once(self, path: str, body: dict[str, Any]) -> tuple[bytes, float]:
        """One POST: the raw reply and its latency in ms, or an exception of the right kind."""
        self._wait_for_turn()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        start = time.perf_counter()
        # The order matters: HTTPError is a URLError, and both are OSErrors.
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise _Transient(f"no connection within {self.timeout_s:g} s") from exc
            raise ModelUnavailableError(
                f"{self.name}: cannot reach {self.base_url} ({exc.reason}). "
                "Is the server running? See docs/evals.md."
            ) from exc
        except TimeoutError as exc:
            raise _Transient(f"no reply within {self.timeout_s:g} s") from exc
        except (ConnectionError, http.client.HTTPException) as exc:
            raise _Transient(f"connection dropped: {exc!r}") from exc
        return raw, (time.perf_counter() - start) * 1000

    def _http_error(self, exc: urllib.error.HTTPError) -> Exception:
        """Turn an HTTP error status into the right exception (see the module docstring)."""
        try:
            body = exc.read(MAX_ERROR_BODY_BYTES).decode("utf-8", errors="replace")
        except OSError:
            body = ""
        message = self._redact(
            f"{self.name}: HTTP {exc.code} from {self.base_url}: {body[:MAX_MESSAGE_CHARS]}"
        )
        if exc.code == 429 and _DAILY_QUOTA.search(body):
            return QuotaExhaustedError(f"{message}\nDaily quota used up: resume after it resets.")
        if exc.code in TRANSIENT_STATUSES:
            return _Transient(message, _retry_after_s(exc.headers.get("Retry-After"), body))
        if exc.code in CONFIG_STATUSES:
            return ModelConfigError(message)
        return ModelError(message)

    def _redact(self, text: str) -> str:
        """Blank out the API key, in case a server ever echoes it back."""
        if self._api_key:
            return text.replace(self._api_key, "***")
        return text


class ChatClient(_HttpClient):
    """A client for one model behind an OpenAI-compatible chat-completions endpoint.

    `options` are _HttpClient's (api_key, timeout_s, max_retries, backoff_s, min_interval_s).
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        *,
        extra_body: dict[str, Any] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(name, base_url, model, **options)
        self.extra_body = dict(extra_body or {})

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        seed: int | None = None,
    ) -> ModelReply:
        """Send the messages and return the reply, retrying transient failures.

        Raises QuotaExhaustedError, ModelConfigError, ModelUnavailableError or ModelError.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self.extra_body,
        }
        if seed is not None:
            body["seed"] = seed
        return self._call("/chat/completions", body, self._parse_reply)

    def _parse_reply(self, raw: bytes, latency_ms: float) -> ModelReply:
        try:
            payload = json.loads(raw)
            choice = payload["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            preview = raw[:MAX_MESSAGE_CHARS].decode("utf-8", errors="replace")
            raise ModelError(self._redact(f"{self.name}: unexpected reply: {preview}")) from exc
        if choice.get("finish_reason") in FAILED_FINISH_REASONS:
            # Even if some text came back, it is not the model's real answer: retry, never grade.
            preview = raw[:MAX_MESSAGE_CHARS].decode("utf-8", errors="replace")
            raise _Transient(
                self._redact(f"{self.name}: the provider failed mid-answer: {preview}")
            )
        if text is None:
            text = ""  # some providers send null content, e.g. when a safety filter blocks it
        if not isinstance(text, str):
            raise ModelError(f"{self.name}: reply content is a {type(text).__name__}, not text")
        usage = payload.get("usage") or {}
        return ModelReply(
            text=text,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            finish_reason=choice.get("finish_reason"),
        )


class EmbeddingClient(_HttpClient):
    """A client for one embedding model behind an OpenAI-compatible /embeddings endpoint.

    It adds the model's task prefixes and checks every vector (count, size, finite numbers).
    `options` are _HttpClient's (api_key, timeout_s, max_retries, backoff_s, min_interval_s).
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        model: str,
        *,
        info: EmbedderInfo,
        batch_size: int = EMBED_BATCH_SIZE,
        **options: Any,
    ) -> None:
        super().__init__(name, base_url, model, **options)
        self.info = info
        self.dimensions = info.dimensions
        self.batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector per stored text, sent in batches of `batch_size`."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors += self._embed([self.info.document_prefix + text for text in batch])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """The vector of one search question."""
        [vector] = self._embed([self.info.query_prefix + text])
        return vector

    def _embed(self, inputs: list[str]) -> list[list[float]]:
        def parse(raw: bytes, latency_ms: float) -> list[list[float]]:
            return self._parse_vectors(raw, expected=len(inputs))

        return self._call("/embeddings", {"model": self.model, "input": inputs}, parse)

    def _parse_vectors(self, raw: bytes, *, expected: int) -> list[list[float]]:
        try:
            items = sorted(json.loads(raw)["data"], key=lambda item: item["index"])
            vectors = [[float(number) for number in item["embedding"]] for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            preview = raw[:MAX_MESSAGE_CHARS].decode("utf-8", errors="replace")
            raise ModelError(self._redact(f"{self.name}: unexpected reply: {preview}")) from exc
        if len(vectors) != expected:
            raise ModelError(f"{self.name}: sent {expected} texts, got {len(vectors)} vectors")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ModelError(
                    f"{self.name}: a vector has {len(vector)} numbers, expected {self.dimensions}"
                )
            if not all(math.isfinite(number) for number in vector):
                raise ModelError(f"{self.name}: a vector contains NaN or infinity")
        return vectors


def make_client(
    spec: str,
    *,
    rpm: float | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    extra_body: dict[str, Any] | None = None,
) -> ChatClient:
    """A client from a spec like "ollama/qwen2.5-coder:1.5b-instruct-fp16" or "gemini/<model>".

    The spec is also the client's name (it goes into every EvalRecord). `rpm` limits requests
    per minute. The Gemini key comes from the GEMINI_API_KEY environment variable.
    """
    provider, _, model = spec.partition("/")
    if not model:
        raise ValueError(f"model spec {spec!r} needs the form '<provider>/<model>'")
    min_interval_s = 60.0 / rpm if rpm else 0.0
    if provider == "ollama":
        base_url = os.environ.get(OLLAMA_URL_ENV) or OLLAMA_BASE_URL
        return ChatClient(
            spec,
            base_url,
            model,
            timeout_s=timeout_s,
            min_interval_s=min_interval_s,
            extra_body=extra_body,
        )
    if provider == "gemini":
        key = os.environ.get(GEMINI_KEY_ENV, "").strip()
        if not key:
            raise ModelConfigError(
                f"{GEMINI_KEY_ENV} is not set. Put it in .env (see .env.example) and run with "
                "`uv run --env-file .env ...`."
            )
        return ChatClient(
            spec,
            GEMINI_BASE_URL,
            model,
            api_key=key,
            timeout_s=timeout_s,
            min_interval_s=min_interval_s,
            extra_body=extra_body,
        )
    raise ValueError(f"unknown provider {provider!r} in {spec!r}: use 'ollama/...' or 'gemini/...'")


def make_embedder(spec: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> EmbeddingClient:
    """An embedding client from a spec like "ollama/nomic-embed-text" (also its name).

    Only Ollama, and only models in KNOWN_EMBEDDERS: a wrong size or a missing prefix would
    give poor search results without any error, so unknown models are refused.
    """
    provider, _, model = spec.partition("/")
    if provider != "ollama" or not model:
        raise ValueError(f"embedding spec {spec!r} needs the form 'ollama/<model>'")
    info = KNOWN_EMBEDDERS.get(model.split(":")[0])  # "nomic-embed-text:v1.5" is the same model
    if info is None:
        raise ValueError(
            f"unknown embedding model {model!r}: add its size and prefixes to KNOWN_EMBEDDERS"
        )
    base_url = os.environ.get(OLLAMA_URL_ENV) or OLLAMA_BASE_URL
    return EmbeddingClient(spec, base_url, model, info=info, timeout_s=timeout_s)
