"""Tests for the model clients against a tiny fake server on 127.0.0.1 (no internet needed).

The fake server speaks just enough of the OpenAI chat-completions and embeddings formats. Each
test queues the answers it wants (status, body, headers, delay), and the server records every
request. So the tests send real HTTP and never mock the client.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from codetutor.evals import (
    ChatClient,
    ModelConfigError,
    ModelError,
    ModelUnavailableError,
    QuotaExhaustedError,
    make_client,
)
from codetutor.evals.clients import (
    GEMINI_BASE_URL,
    GEMINI_KEY_ENV,
    OLLAMA_URL_ENV,
    EmbedderInfo,
    EmbeddingClient,
    make_embedder,
)

KEY = "test-key-12345"
MESSAGES = [{"role": "user", "content": "Write f."}]
CODE_REPLY = "```python\ndef f(n):\n    return n\n```"


@dataclass
class Answer:
    """What the fake server sends back for one request."""

    status: int = 200
    body: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    delay_s: float = 0.0


@dataclass
class Seen:
    """One request, as the fake server received it."""

    path: str
    authorization: str | None
    body: dict[str, Any]
    at: float  # time.monotonic() when it arrived


def ok(content: str | None = CODE_REPLY, finish_reason: str = "stop") -> Answer:
    """A successful chat-completions reply."""
    payload = {
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "total_tokens": 100},
    }
    return Answer(body=json.dumps(payload))


class FakeServer:
    """An OpenAI-compatible server on a free local port, answering from a queue."""

    def __init__(self) -> None:
        self.answers: list[Answer] = []
        self.seen: list[Seen] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                auth = self.headers.get("Authorization")
                fake.seen.append(Seen(self.path, auth, body, time.monotonic()))
                answer = fake.answers.pop(0) if fake.answers else Answer(500, "nothing queued")
                time.sleep(answer.delay_s)
                data = answer.body.encode("utf-8")
                try:
                    self.send_response(answer.status)
                    for name, value in answer.headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # the client already gave up (timeout tests)

            def log_message(self, format: str, *args: Any) -> None:
                pass  # keep test output quiet

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._httpd.server_port}/v1"
        # A short poll interval: shutdown() waits up to one interval (default 0.5 s per test).
        serve = threading.Thread(target=self._httpd.serve_forever, args=(0.01,), daemon=True)
        serve.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer()
    yield fake
    fake.close()


def client_for(server: FakeServer, **options: Any) -> ChatClient:
    """A client with fast test settings (tiny backoff), overridable per test."""
    settings: dict[str, Any] = {"max_retries": 2, "backoff_s": 0.01, "timeout_s": 5.0}
    settings.update(options)
    return ChatClient("test/model-x", server.url, "model-x", **settings)


def _complete(client: ChatClient, seed: int | None = None) -> Any:
    return client.complete(MESSAGES, temperature=0.2, max_tokens=256, seed=seed)


# --- success ---


def test_sends_the_request_and_parses_the_reply(server: FakeServer) -> None:
    server.answers.append(ok(finish_reason="length"))
    reply = _complete(client_for(server), seed=7)
    assert reply.text == CODE_REPLY
    assert (reply.prompt_tokens, reply.completion_tokens, reply.total_tokens) == (12, 34, 100)
    assert reply.finish_reason == "length"
    assert reply.latency_ms is not None and reply.latency_ms > 0
    [request] = server.seen
    assert request.path == "/v1/chat/completions"
    assert request.body == {
        "model": "model-x",
        "messages": MESSAGES,
        "temperature": 0.2,
        "max_tokens": 256,
        "seed": 7,
    }


def test_no_seed_means_no_seed_field_and_extra_body_is_sent(server: FakeServer) -> None:
    server.answers.append(ok())
    _complete(client_for(server, extra_body={"reasoning_effort": "none"}))
    [request] = server.seen
    assert "seed" not in request.body
    assert request.body["reasoning_effort"] == "none"


def test_key_is_sent_only_when_set(server: FakeServer) -> None:
    server.answers += [ok(), ok()]
    _complete(client_for(server))
    _complete(client_for(server, api_key=KEY))
    assert [request.authorization for request in server.seen] == [None, f"Bearer {KEY}"]


def test_null_content_is_an_empty_reply(server: FakeServer) -> None:
    server.answers.append(ok(content=None, finish_reason="content_filter"))
    reply = _complete(client_for(server))
    assert (reply.text, reply.finish_reason) == ("", "content_filter")


# --- transient failures: retry ---


def test_rate_limit_waits_as_long_as_the_server_asks(server: FakeServer) -> None:
    server.answers += [Answer(429, '{"error": "slow down"}', {"Retry-After": "0.3"}), ok()]
    _complete(client_for(server, backoff_s=0.001))  # our own backoff alone would be ~0 s
    first, second = server.seen
    assert second.at - first.at >= 0.25


def test_gemini_retry_delay_in_the_body_is_honoured(server: FakeServer) -> None:
    body = json.dumps({"error": {"code": 429, "details": [{"retryDelay": "0.3s"}]}})
    server.answers += [Answer(429, body), ok()]
    _complete(client_for(server, backoff_s=0.001))
    first, second = server.seen
    assert second.at - first.at >= 0.25


def test_server_errors_are_retried_then_given_up(server: FakeServer) -> None:
    server.answers += [Answer(503, "busy")] * 3
    with pytest.raises(ModelError, match="gave up after 3 tries") as caught:
        _complete(client_for(server, max_retries=2))
    assert type(caught.value) is ModelError  # not a config or quota error
    assert len(server.seen) == 3


def test_slow_server_times_out_and_is_retried(server: FakeServer) -> None:
    server.answers += [Answer(delay_s=0.5, body="late")] * 2
    with pytest.raises(ModelError, match="no reply within 0.1 s"):
        _complete(client_for(server, timeout_s=0.1, max_retries=1))
    assert len(server.seen) == 2


def test_finish_reason_error_is_retried(server: FakeServer) -> None:
    # HTTP 200, but the provider failed mid-answer (seen on OpenRouter's free tier).
    server.answers += [ok(content="", finish_reason="error"), ok()]
    reply = _complete(client_for(server))
    assert (reply.text, reply.finish_reason) == (CODE_REPLY, "stop")
    assert len(server.seen) == 2


def test_finish_reason_error_gives_up_as_a_model_error(server: FakeServer) -> None:
    half_answer = "```python\ndef f(n):\n    re"  # some text came back: still not an answer
    server.answers += [ok(content=half_answer, finish_reason="error")] * 3
    with pytest.raises(ModelError, match="gave up after 3 tries") as caught:
        _complete(client_for(server, max_retries=2))
    assert type(caught.value) is ModelError  # a failed call: the harness never grades it
    assert len(server.seen) == 3


# --- failures that must not be retried ---


def test_wrong_key_fails_at_once_and_never_shows_the_key(server: FakeServer) -> None:
    server.answers.append(Answer(401, json.dumps({"error": f"API key {KEY} not valid"})))
    with pytest.raises(ModelConfigError) as caught:
        _complete(client_for(server, api_key=KEY))
    assert len(server.seen) == 1
    assert KEY not in str(caught.value)
    assert "***" in str(caught.value)


def test_daily_quota_stops_at_once(server: FakeServer) -> None:
    detail = {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
    error = {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [detail]}
    body = json.dumps([{"error": error}])
    server.answers.append(Answer(429, body))
    with pytest.raises(QuotaExhaustedError):
        _complete(client_for(server))
    assert len(server.seen) == 1


def test_closed_port_is_unavailable() -> None:
    with socket.socket() as probe:  # find a free port, then close it: nothing listens there
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/v1"
    client = ChatClient("test/model-x", url, "model-x", max_retries=0)
    with pytest.raises(ModelUnavailableError, match=f"cannot reach {url}"):
        _complete(client)


@pytest.mark.parametrize(
    "body",
    ["not json", '{"choices": []}', '{"choices": [{"message": {"content": 5}}]}'],
    ids=["not_json", "no_choices", "content_not_text"],
)
def test_bad_replies_are_model_errors(server: FakeServer, body: str) -> None:
    server.answers.append(Answer(200, body))
    with pytest.raises(ModelError):
        _complete(client_for(server))
    assert len(server.seen) == 1


# --- throttle ---


def test_throttle_keeps_a_gap_between_requests(server: FakeServer) -> None:
    server.answers += [ok(), ok()]
    client = client_for(server, min_interval_s=0.2)
    _complete(client)
    _complete(client)
    first, second = server.seen
    assert second.at - first.at >= 0.19


# --- make_client ---


def test_make_client_for_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OLLAMA_URL_ENV, "http://example.test:1/v1")
    client = make_client("ollama/qwen2.5-coder:1.5b-instruct-fp16", rpm=30)
    assert client.name == "ollama/qwen2.5-coder:1.5b-instruct-fp16"
    assert client.model == "qwen2.5-coder:1.5b-instruct-fp16"
    assert client.base_url == "http://example.test:1/v1"
    assert client.min_interval_s == 2.0


def test_make_client_for_gemini_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GEMINI_KEY_ENV, raising=False)
    with pytest.raises(ModelConfigError, match=r"\.env"):
        make_client("gemini/some-flash-model")


def test_make_client_for_gemini_hides_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GEMINI_KEY_ENV, KEY)
    client = make_client("gemini/some-flash-model")
    assert client.base_url == GEMINI_BASE_URL
    assert KEY not in repr(client)


@pytest.mark.parametrize("spec", ["openai/gpt-x", "qwen-without-provider", "ollama/"])
def test_make_client_rejects_bad_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        make_client(spec)


# --- embeddings (Week 4) ---

INFO = EmbedderInfo(3, document_prefix="doc: ", query_prefix="q: ")


def vectors(*rows: list[float], shuffle: bool = False) -> Answer:
    """A successful /embeddings reply, with each row's index (optionally in reverse order)."""
    data = [{"object": "embedding", "index": i, "embedding": row} for i, row in enumerate(rows)]
    payload = {"object": "list", "data": data[::-1] if shuffle else data}
    return Answer(body=json.dumps(payload))


def embedder_for(server: FakeServer, **options: Any) -> EmbeddingClient:
    settings: dict[str, Any] = {"max_retries": 1, "backoff_s": 0.01, "timeout_s": 5.0}
    settings.update(options)
    return EmbeddingClient("test/embed", server.url, "embed", info=INFO, **settings)


def test_embeddings_add_the_prefixes_and_keep_the_order(server: FakeServer) -> None:
    server.answers += [vectors([1, 0, 0], [0, 1, 0], shuffle=True), vectors([0, 0, 1])]
    client = embedder_for(server)
    assert client.embed_documents(["a", "b"]) == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert client.embed_query("c") == [0.0, 0.0, 1.0]
    assert server.seen[0].path == "/v1/embeddings"
    assert server.seen[0].body == {"model": "embed", "input": ["doc: a", "doc: b"]}
    assert server.seen[1].body["input"] == ["q: c"]


def test_embeddings_are_sent_in_batches(server: FakeServer) -> None:
    server.answers += [vectors([1, 0, 0], [1, 0, 0]), vectors([0, 1, 0])]
    client = embedder_for(server, batch_size=2)
    assert len(client.embed_documents(["a", "b", "c"])) == 3
    assert [len(seen.body["input"]) for seen in server.seen] == [2, 1]


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (vectors([1, 0, 0]), "sent 2 texts, got 1 vectors"),
        (vectors([1, 0], [0, 1]), "has 2 numbers, expected 3"),
        (Answer(body='{"data": [{"index": 0, "embedding": "nope"}]}'), "unexpected reply"),
    ],
)
def test_bad_embedding_replies_are_errors(server: FakeServer, answer: Answer, message: str) -> None:
    server.answers.append(answer)
    with pytest.raises(ModelError, match=message):
        embedder_for(server).embed_documents(["a", "b"])


def test_a_non_finite_number_in_a_vector_is_an_error(server: FakeServer) -> None:
    # JSON has no NaN, but Python's json module (and some servers) write it anyway.
    server.answers.append(Answer(body='{"data": [{"index": 0, "embedding": [1, NaN, 0]}]}'))
    with pytest.raises(ModelError, match="NaN or infinity"):
        embedder_for(server).embed_query("a")


def test_a_missing_embedding_model_says_so(server: FakeServer) -> None:
    # What Ollama 0.35 answers for a model that was never pulled (seen live, 2026-10-02).
    body = '{"error":{"message":"model \\"embed\\" not found, try pulling it first"}}'
    server.answers.append(Answer(404, body))
    with pytest.raises(ModelConfigError, match="try pulling it first"):
        embedder_for(server).embed_query("a")


def test_embeddings_retry_a_busy_server(server: FakeServer) -> None:
    server.answers += [Answer(503, "busy"), vectors([0, 1, 0])]
    assert embedder_for(server).embed_query("a") == [0.0, 1.0, 0.0]
    assert len(server.seen) == 2


def test_make_embedder_knows_nomic_embed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OLLAMA_URL_ENV, "http://127.0.0.1:9/v1")
    client = make_embedder("ollama/nomic-embed-text:v1.5")
    assert (client.name, client.model, client.dimensions) == (
        "ollama/nomic-embed-text:v1.5",
        "nomic-embed-text:v1.5",
        768,
    )
    assert client.info.query_prefix == "search_query: "
    assert client.base_url == "http://127.0.0.1:9/v1"


@pytest.mark.parametrize(
    "spec", ["gemini/text-embedding-004", "ollama/", "ollama/some-unknown-embedder", "nomic"]
)
def test_make_embedder_rejects_bad_or_unknown_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        make_embedder(spec)
