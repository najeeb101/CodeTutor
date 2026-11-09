"""End-to-end checks of a running stack: API + workers, and optionally the web UI (Weeks 3-4).

It walks through the app like a student: health, problem list, problem view, log in, submit the
reference solution (must be accepted), submit a buggy solution (must fail, with hidden tests
staying hidden), "my submissions", then ask the tutor for a hint about the buggy submission
(no solution line, no trace fields) and rate it. Each step is a `Check`; the run stops at the first
failure, with a message that says what to start or fix.

Standard library only (urllib). `scripts/e2e_check.py` (`make e2e`) runs it against the dev
stack; tests/test_e2e.py runs it against a real uvicorn server started inside the test.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any

from codetutor.api.auth import SESSION_COOKIE
from codetutor.problems import Problem
from codetutor.tutor.guardrail import solution_lines

HTTP_TIMEOUT_S = 10.0
# The first request to the API only checks that it is up. On WSL a port nobody listens on times
# out instead of refusing (mirrored networking), so this one gives up sooner.
PROBE_TIMEOUT_S = 3.0
POLL_INTERVAL_S = 0.5
RESULT_TIMEOUT_S = 60.0  # the slowest bank problem needs ~38 s in Docker
HINT_TIMEOUT_S = 150.0  # loading the model after a reboot took 109 s
# Every field a hint answer may have (api/schemas.py HintOut): never the trace.
HINT_FIELDS = {
    "id",
    "problem_id",
    "problem_version",
    "submission_id",
    "level",
    "question",
    "created_at",
    "job_status",
    "text",
    "source",
    "rating",
    "message",
}
DISPLAY_FIELDS = ("input", "expected", "actual", "args_repr", "expected_repr", "actual_repr")


class E2EFailure(Exception):
    """A check failed. The message says what went wrong and, if possible, what to do."""


@dataclass(frozen=True)
class Check:
    """The outcome of one step."""

    name: str
    ok: bool
    detail: str
    seconds: float


@dataclass(frozen=True)
class Response:
    """An HTTP answer (any status: checking it is the caller's job)."""

    status: int
    headers: dict[str, str]  # lower-case names
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)

    def page_text(self) -> str:
        """An HTML page as text: entities decoded, React's <!-- --> text separators removed."""
        return html.unescape(self.body.decode("utf-8").replace("<!-- -->", ""))


def request(
    method: str,
    url: str,
    *,
    body: object = None,
    headers: dict[str, str] | None = None,
    timeout_s: float = HTTP_TIMEOUT_S,
) -> Response:
    """One HTTP request. Raises E2EFailure only when the server can't be reached."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    all_headers = {"Content-Type": "application/json"} if body is not None else {}
    all_headers |= headers or {}
    req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as answer:
            return Response(answer.status, _lower(answer.headers.items()), answer.read())
    except urllib.error.HTTPError as error:  # a 4xx/5xx answer is still an answer
        return Response(error.code, _lower(error.headers.items()), error.read())
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        raise E2EFailure(f"cannot reach {url} ({reason})") from exc


def _lower(items: Any) -> dict[str, str]:
    return {name.lower(): value for name, value in items}


def forbidden_texts(problem: Problem) -> list[str]:
    """Texts a student must never receive: the hints and the solution's own lines.

    The same lines the tutor's guardrail checks (`solution_lines`): lines also in the starter
    code or the description (e.g. the `def` line) and trivial ones (`return result`) are left out.
    """
    return [*problem.hints, *solution_lines(problem)]


def _strings(value: Any) -> Iterator[str]:
    """Every string inside a JSON value (keys too)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)


def _has_details(test: dict[str, Any]) -> bool:
    """Does a test result carry anything a hidden test must not show?"""
    return test["revealed"] or any(test[name] is not None for name in DISPLAY_FIELDS)


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


def _expect_status(response: Response, status: int, what: str) -> None:
    if response.status != status:
        raise E2EFailure(
            f"{what}: HTTP {response.status}, expected {status}: {response.body[:200]!r}"
        )


@dataclass
class _Run:
    """State shared by the steps of one run."""

    api: str
    web: str | None
    problem: Problem
    result_timeout_s: float
    hint_timeout_s: float = HINT_TIMEOUT_S
    user_name: str = field(default_factory=lambda: f"e2e-{time.time_ns() // 1_000_000}")
    user_headers: dict[str, str] = field(default_factory=dict)
    submission_ids: list[int] = field(default_factory=list)
    hint_id: int | None = None

    @property
    def base(self) -> str:
        """Where student requests go: through the web server's /api rewrite when it's checked."""
        return self.web or self.api

    # --- the steps (each returns a short detail text or raises E2EFailure) ---

    def health(self) -> str:
        try:
            response = request("GET", f"{self.api}/api/health", timeout_s=PROBE_TIMEOUT_S)
        except E2EFailure as failure:
            raise E2EFailure(f"{failure}: is `make api` running?") from failure
        _expect_status(response, 200, "GET /api/health (is the database up? `make db-up`)")
        return "database reachable"

    def problem_list(self) -> str:
        response = request("GET", f"{self.api}/api/problems")
        _expect_status(response, 200, "GET /api/problems")
        ids = [item["id"] for item in response.json()]
        _expect(self.problem.id in ids, f"{self.problem.id} is not listed: run `make db-sync`")
        return f"{len(ids)} problems"

    def problem_view(self) -> str:
        response = request("GET", f"{self.api}/api/problems/{self.problem.id}")
        _expect_status(response, 200, f"GET /api/problems/{self.problem.id}")
        view = response.json()
        _expect(
            view["version"] == self.problem.version,
            f"the API serves version {view['version']}, the files say {self.problem.version}: "
            "run `make db-sync`",
        )
        visible = [test.id for test in self.problem.visible_tests]
        _expect(
            [e["id"] for e in view["examples"]] == visible, "examples are not the visible tests"
        )
        texts = list(_strings(view))
        leaked = [s for s in forbidden_texts(self.problem) if any(s in text for text in texts)]
        _expect(not leaked, f"the problem view contains hidden text: {leaked}")
        return f"{len(visible)} visible tests, no hints or solution lines"

    def web_list_page(self) -> str:
        try:
            response = request("GET", f"{self.web}/")
        except E2EFailure as failure:
            raise E2EFailure(f"{failure}: is `make web` running?") from failure
        _expect_status(response, 200, "GET /")
        listed = request("GET", f"{self.api}/api/problems").json()
        links = set(re.findall(r'href="/problems/([^"]+)"', response.body.decode("utf-8")))
        missing = {item["id"] for item in listed} - links
        _expect(not missing, f"the list page has no link for {sorted(missing)}")
        return f"{len(links)} problem links"

    def web_problem_page(self) -> str:
        response = request("GET", f"{self.web}/problems/{self.problem.id}")
        _expect_status(response, 200, f"GET /problems/{self.problem.id}")
        text = response.page_text()
        view = request("GET", f"{self.api}/api/problems/{self.problem.id}").json()
        for example in view["examples"]:
            shown = f"{view['function_name']}({example['args_repr']})"
            _expect(shown in text and example["expected_repr"] in text, f"{shown} is not shown")
        leaked = [s for s in forbidden_texts(self.problem) if s in text]
        _expect(not leaked, f"the page contains hidden text: {leaked}")
        return "visible tests shown in Python style, no hints or solution lines"

    def login(self) -> str:
        response = request("POST", f"{self.base}/api/guest")
        _expect_status(response, 200, "POST /api/guest")
        cookie = SimpleCookie(response.headers.get("set-cookie", ""))
        _expect(SESSION_COOKIE in cookie, "POST /api/guest set no session cookie")
        _expect("httponly" in response.headers["set-cookie"].lower(), "the cookie is not HttpOnly")
        self.user_headers = {"Cookie": f"{SESSION_COOKIE}={cookie[SESSION_COOKIE].value}"}
        self.user_name = response.json()["name"]
        return f"guest {self.user_name!r} (session cookie)"

    def _submit_and_wait(self, code: str) -> dict[str, Any]:
        body = {
            "problem_id": self.problem.id,
            "problem_version": self.problem.version,
            "code": code,
        }
        response = request(
            "POST", f"{self.base}/api/submissions", body=body, headers=self.user_headers
        )
        _expect_status(response, 202, "POST /api/submissions")
        submission_id = response.json()["id"]
        _expect(
            response.headers.get("location") == f"/api/submissions/{submission_id}",
            "no Location header",
        )
        self.submission_ids.append(submission_id)
        deadline = time.monotonic() + self.result_timeout_s
        while time.monotonic() < deadline:
            response = request(
                "GET", f"{self.base}/api/submissions/{submission_id}", headers=self.user_headers
            )
            _expect_status(response, 200, f"GET /api/submissions/{submission_id}")
            submission = response.json()
            if submission["job_status"] == "done":
                return submission
            _expect(
                submission["job_status"] != "failed", f"grading failed: {submission['message']}"
            )
            time.sleep(POLL_INTERVAL_S)
        raise E2EFailure(f"no result after {self.result_timeout_s:g} s: is `make worker` running?")

    def solution_accepted(self) -> str:
        result = self._submit_and_wait(self.problem.solution_code)["result"]
        _expect(
            result["status"] == "accepted" and result["passed"] == len(self.problem.tests),
            f"the reference solution got {result['status']} {result['passed']}/{result['total']}",
        )
        return f"accepted {result['passed']}/{result['total']}"

    def buggy_fails_and_hidden_stays_hidden(self) -> str:
        name, code = sorted(self.problem.buggy.items())[0]
        result = self._submit_and_wait(code)["result"]
        _expect(result["status"] != "accepted", f"buggy/{name}.py was accepted")
        hidden = [test for test in result["tests"] if test["hidden"]]
        _expect(len(hidden) == len(self.problem.hidden_tests), "hidden tests are missing")
        shown = [test["test_id"] for test in hidden if _has_details(test)]
        _expect(not shown, f"hidden tests with details: {shown}")
        failed = sum(test["status"] != "passed" for test in hidden)
        score = f"{result['status']} {result['passed']}/{result['total']}"
        return f"buggy/{name}.py: {score}, {failed} hidden failures without details"

    def my_submissions(self) -> str:
        response = request(
            "GET",
            f"{self.base}/api/submissions?problem_id={self.problem.id}&limit=5",
            headers=self.user_headers,
        )
        _expect_status(response, 200, "GET /api/submissions")
        newest = [item["id"] for item in response.json()][: len(self.submission_ids)]
        _expect(
            newest == self.submission_ids[::-1],
            f"expected {self.submission_ids[::-1]}, got {newest}",
        )
        return f"{len(newest)} submissions, newest first"

    def hint(self) -> str:
        body = {
            "problem_id": self.problem.id,
            "problem_version": self.problem.version,
            "level": 1,
            "submission_id": self.submission_ids[-1],  # the buggy one
        }
        response = request("POST", f"{self.base}/api/hints", body=body, headers=self.user_headers)
        _expect_status(response, 202, "POST /api/hints")
        self.hint_id = response.json()["id"]
        deadline = time.monotonic() + self.hint_timeout_s
        while time.monotonic() < deadline:
            response = request(
                "GET", f"{self.base}/api/hints/{self.hint_id}", headers=self.user_headers
            )
            _expect_status(response, 200, f"GET /api/hints/{self.hint_id}")
            hint = response.json()
            _expect(hint["job_status"] != "failed", f"the hint failed: {hint['message']}")
            if hint["job_status"] == "done":
                return self._check_hint(hint)
            time.sleep(POLL_INTERVAL_S)
        raise E2EFailure(f"no hint after {self.hint_timeout_s:g} s: is `make tutor` running?")

    def _check_hint(self, hint: dict[str, Any]) -> str:
        _expect(set(hint) == HINT_FIELDS, f"unexpected hint fields: {sorted(set(hint))}")
        # The teacher's hints 1-2 may be shown (a fallback); the solution's lines never.
        leaked = [line for line in solution_lines(self.problem) if line in hint["text"]]
        _expect(not leaked, f"the hint contains solution lines: {leaked}")
        words = len(hint["text"].split())
        return f"{hint['source']} hint, {words} words, no solution line"

    def rating(self) -> str:
        response = request(
            "PUT",
            f"{self.base}/api/hints/{self.hint_id}/rating",
            body={"rating": 1},
            headers=self.user_headers,
        )
        _expect_status(response, 200, f"PUT /api/hints/{self.hint_id}/rating")
        _expect(response.json()["rating"] == 1, "the rating was not saved")
        return "👍 saved"


def run_checks(
    api_url: str,
    problem: Problem,
    *,
    web_url: str | None = None,
    result_timeout_s: float = RESULT_TIMEOUT_S,
    hint_timeout_s: float = HINT_TIMEOUT_S,
    hints: bool = True,
) -> list[Check]:
    """Run every step in order, stopping at the first failure. Returns the checks done.

    `hints=False` leaves out the two tutor steps, for a stack without a tutor worker (the
    containers before Deploy Step 4, or a server whose tutor is down).
    """
    run = _Run(
        api_url.rstrip("/"),
        web_url.rstrip("/") if web_url else None,
        problem,
        result_timeout_s,
        hint_timeout_s,
    )
    steps: list[tuple[str, Callable[[], str]]] = [
        ("API health", run.health),
        ("problem list", run.problem_list),
        ("problem view hides the secrets", run.problem_view),
    ]
    if run.web:
        steps += [
            ("web: problem list page", run.web_list_page),
            ("web: problem page", run.web_problem_page),
        ]
    steps += [
        ("start a guest session", run.login),
        ("reference solution is accepted", run.solution_accepted),
        ("buggy solution fails, hidden tests stay hidden", run.buggy_fails_and_hidden_stays_hidden),
        ("my submissions", run.my_submissions),
    ]
    if hints:
        steps += [
            ("a hint about the buggy submission", run.hint),
            ("rate the hint", run.rating),
        ]
    checks: list[Check] = []
    for name, step in steps:
        start = time.monotonic()
        try:
            detail = step()
        except E2EFailure as failure:
            checks.append(Check(name, False, str(failure), time.monotonic() - start))
            break
        checks.append(Check(name, True, detail, time.monotonic() - start))
    return checks
