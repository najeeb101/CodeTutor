"""Talk to chat models over HTTP: one small client for both Ollama and Gemini.

Both accept the OpenAI "chat completions" format, so one client covers both; only the base URL
and the API key differ. Standard library only (urllib + json): no SDK and no LiteLLM (decision
2026-10-01).

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
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Protocol

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


def _retry_after_s(header: str | None, body: str) -> float | None:
    """The wait the server asked for: the Retry-After header, else Gemini's retryDelay."""
    if header:
        try:
            return float(header)
        except ValueError:
            pass  # an HTTP date instead of seconds: fall back to our own backoff
    match = _RETRY_DELAY.search(body)
    return float(match[1]) if match else None


class ChatClient:
    """A client for one model behind an OpenAI-compatible chat-completions endpoint.

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
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.min_interval_s = min_interval_s
        self.extra_body = dict(extra_body or {})
        self._lock = threading.Lock()
        self._next_start = 0.0  # time.monotonic() before which no request may start

    def __repr__(self) -> str:
        # Never show the key, so it can't end up in logs or tracebacks.
        return f"ChatClient(name={self.name!r}, base_url={self.base_url!r}, model={self.model!r})"

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
        attempt = 0
        while True:
            try:
                return self._post_once(body)
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

    def _post_once(self, body: dict[str, Any]) -> ModelReply:
        self._wait_for_turn()
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
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
        latency_ms = (time.perf_counter() - start) * 1000
        return self._parse_reply(raw, latency_ms)

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

    def _redact(self, text: str) -> str:
        """Blank out the API key, in case a server ever echoes it back."""
        if self._api_key:
            return text.replace(self._api_key, "***")
        return text


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
