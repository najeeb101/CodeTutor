"""Fake "models" for tests and dry runs: no network, known answers.

They cheat on purpose: they read the internal Problem (solution, buggy files), which a real model
never sees. That is what makes them useful. The oracle must score 1.0 on every problem, so if it
doesn't, the bug is in our pipeline (prompt → reply → extract → grade → record), not in a model.
"""

from __future__ import annotations

from collections.abc import Callable

from codetutor.evals.records import ModelReply
from codetutor.problems import Problem

FakeModel = Callable[[Problem], ModelReply]


def _fenced(code: str) -> str:
    return f"```python\n{code.strip()}\n```"


def oracle(problem: Problem) -> ModelReply:
    """Replies with the reference solution: should always be accepted."""
    return ModelReply(text=_fenced(problem.solution_code))


def starter(problem: Problem) -> ModelReply:
    """Replies with the unchanged starter code: should never be accepted."""
    return ModelReply(text=_fenced(problem.starter_code))


def buggy(problem: Problem) -> ModelReply:
    """Replies with the first buggy solution (by name): should never be accepted."""
    first = sorted(problem.buggy)[0]
    return ModelReply(text=_fenced(problem.buggy[first]))


def chatty(problem: Problem) -> ModelReply:
    """The reference solution, hidden among prose, a draft and an example-usage block.

    Tests the extraction rule "the last block that defines the function", on real problems.
    """
    first_input = problem.visible_tests[0].input
    call = f"{problem.function_name}({', '.join(repr(arg) for arg in first_input)})"
    text = (
        "Sure! Let's solve it step by step.\n\n"
        f"A first draft:\n{_fenced(problem.starter_code)}\n\n"
        "That draft does nothing yet. Here is the final version:\n\n"
        f"{_fenced(problem.solution_code)}\n\n"
        f"Example usage:\n{_fenced(f'print({call})')}\n"
    )
    return ModelReply(text=text)


FAKE_MODELS: dict[str, FakeModel] = {
    "fake/oracle": oracle,
    "fake/starter": starter,
    "fake/buggy": buggy,
    "fake/chatty": chatty,
}
