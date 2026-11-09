"""Guards in front of the endpoints (Deploy Step 2a): body size, the client's IP, per-IP counts.

All the numbers live in `RateLimits` (api/submissions.py); this module only enforces them.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE_BODY = b'{"detail":"request too large"}'
MAX_IP_KEYS = 10_000  # above this, forget addresses whose requests all left the window


class _TooLarge(Exception):
    """Raised inside `receive` when the body passes the limit."""


class BodySizeLimit:
    """Answer 413 to a request body larger than `max_bytes`, without reading it all.

    uvicorn hands the app the whole body, however large. A declared Content-Length over the
    limit is refused at once; a streamed body (no length, chunked) is counted while it is read
    and cut off at the limit. Pure ASGI, so it sees the bytes before FastAPI parses anything.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await _send_413(send)
            return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:  # an answer already on its way can't be replaced
                await _send_413(send)


async def _send_413(send: Send) -> None:
    headers = [(b"content-type", b"application/json"), (b"connection", b"close")]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": TOO_LARGE_BODY})


def client_ip(headers: Mapping[str, str], socket_host: str, trusted_hops: int) -> str:
    """The visitor's address, trusting exactly `trusted_hops` proxies in front of the API.

    Each proxy appends the address it got the request from to X-Forwarded-For, so the entry
    `trusted_hops` places from the right was written by our first proxy. Entries further left
    were written by the visitor (anything at all) and are ignored. With 0 trusted proxies, or a
    request that didn't come through them, the socket's address is the answer.
    """
    if trusted_hops <= 0:
        return socket_host
    forwarded = headers.get("x-forwarded-for")
    entries = [entry.strip() for entry in forwarded.split(",")] if forwarded else []
    if len(entries) < trusted_hops:
        return socket_host
    return entries[-trusted_hops] or socket_host


class IpWindow:
    """At most `limit` events per key in any `window_s` seconds (a sliding window, in memory).

    Kept in memory on purpose: it only slows down one address creating many guests, one API
    process serves the site, and a restart forgetting the counts is harmless. Global limits are
    counted in Postgres instead. Thread-safe: FastAPI runs `def` endpoints in a thread pool.
    """

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, now: float | None = None) -> int | None:
        """Count one event for `key`: None if allowed, else the seconds to wait (not counted)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if len(self._events) > MAX_IP_KEYS:
                self._forget_idle(now)
            events = self._events.setdefault(key, deque())
            while events and events[0] <= now - self.window_s:
                events.popleft()
            if len(events) >= self.limit:
                return max(1, math.ceil(events[0] + self.window_s - now))
            events.append(now)
            return None

    def _forget_idle(self, now: float) -> None:
        cutoff = now - self.window_s
        idle = [key for key, events in self._events.items() if not events or events[-1] <= cutoff]
        for key in idle:
            del self._events[key]
