"""Build the prompt a model gets in an eval.

A model sees exactly what a student sees. `build_messages` takes a StudentProblem, which has no
solution, no hints and no hidden tests, so nothing hidden can leak into a prompt by mistake.
"""

from __future__ import annotations

from pydantic import JsonValue

from codetutor.problems import CompareMode, StudentProblem, VisibleTest

# Bump whenever the text below changes: a different prompt gives different scores, so every
# saved result records the version that produced it.
PROMPT_VERSION = "1"

SYSTEM_PROMPT = (
    "You are an expert Python programmer. You solve programming exercises correctly and "
    "reply with complete, working code."
)


def _call(function_name: str, args: list[JsonValue]) -> str:
    """A Python call as text, e.g. fizzbuzz(5)."""
    return f"{function_name}({', '.join(repr(arg) for arg in args)})"


def _example_line(problem: StudentProblem, example: VisibleTest) -> str:
    line = f"{_call(problem.function_name, example.input)} -> {example.expected!r}"
    if example.compare == CompareMode.FLOAT:
        line += "  (floats are compared with a small tolerance)"
    elif example.compare == CompareMode.UNORDERED:
        line += "  (any order)"
    return line


def _rules(problem: StudentProblem) -> list[str]:
    rules = [
        f"Write the function `{problem.function_name}` in Python 3, with the same parameters "
        "as the starter code.",
        "Return the answer. Do not print it, and do not use input().",
        "Use only the Python standard library.",
        "Hidden tests check more cases than the visible ones, so handle everything the "
        "description says.",
    ]
    if problem.check_input_unchanged:
        rules.append(
            "Do not change the arguments you are given (for example, do not sort or modify a "
            "list argument). Build and return a new value."
        )
    rules.append("Reply with the complete function in one ```python code block.")
    return rules


def build_user_prompt(problem: StudentProblem) -> str:
    """The problem as text: title, description, visible tests, starter code and rules."""
    examples = "\n".join(f"    {_example_line(problem, test)}" for test in problem.examples)
    rules = "\n".join(f"- {rule}" for rule in _rules(problem))
    return (
        f"## {problem.title}\n\n"
        f"{problem.description_en.strip()}\n\n"
        f"### Visible tests\n{examples}\n\n"
        f"### Starter code\n```python\n{problem.starter_code.strip()}\n```\n\n"
        f"### Rules\n{rules}\n"
    )


def build_messages(problem: StudentProblem) -> list[dict[str, str]]:
    """The chat messages for one problem, in the usual {"role": ..., "content": ...} format."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(problem)},
    ]
