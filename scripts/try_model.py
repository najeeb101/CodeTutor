"""Ask one model to solve one problem, then grade the answer (a manual check of a model setup).

Usage:
    uv run --env-file .env python scripts/try_model.py ollama/qwen2.5-coder:1.5b-instruct-fp16 \\
        cs1.loops.fizzbuzz
    uv run --env-file .env python scripts/try_model.py gemini/<model> cs1.loops.fizzbuzz --rpm 5
    ... --show-prompt          print the exact messages sent to the model
    ... --sandbox subprocess   grade without Docker (only for code you trust)

Nothing is saved: full runs with results files come from the run harness (Week 2, Step 3).
"""

from __future__ import annotations

import argparse
import sys

from codetutor.evals import ModelError, build_messages, make_client, score_reply
from codetutor.grader import (
    DockerSandbox,
    Sandbox,
    SandboxUnavailableError,
    SubprocessSandbox,
    TestStatus,
)
from codetutor.problems import ProblemError, get_problem


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", help="e.g. ollama/qwen2.5-coder:1.5b-instruct-fp16")
    parser.add_argument("problem_id", help="e.g. cs1.loops.fizzbuzz")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--rpm", type=float, default=None, help="max requests per minute")
    parser.add_argument(
        "--sandbox",
        choices=["docker", "subprocess"],
        default="docker",
        help="where the model's code runs (default docker: model code is untrusted)",
    )
    parser.add_argument("--show-prompt", action="store_true", help="print the messages sent")
    args = parser.parse_args()

    try:
        problem = get_problem(args.problem_id)
        client = make_client(args.model, rpm=args.rpm)
        sandbox: Sandbox = DockerSandbox() if args.sandbox == "docker" else SubprocessSandbox()
    except (ProblemError, ModelError, ValueError, SandboxUnavailableError) as exc:
        parser.error(str(exc))

    messages = build_messages(problem.to_student_view())
    if args.show_prompt:
        for message in messages:
            print(f"--- {message['role']} ---\n{message['content']}")
    try:
        reply = client.complete(
            messages, temperature=args.temperature, max_tokens=args.max_tokens, seed=args.seed
        )
    except ModelError as exc:
        print(f"Model call failed: {exc}", file=sys.stderr)
        return 1

    record = score_reply(
        problem,
        reply,
        model=args.model,
        temperature=args.temperature,
        sample_index=0,
        sandbox=sandbox,
    )
    print(
        f"--- reply: {reply.prompt_tokens} tokens in, {reply.completion_tokens} out, "
        f"{reply.latency_ms:.0f} ms, finish_reason={reply.finish_reason} ---"
    )
    print(reply.text.rstrip())
    result = record.result
    marks = "".join("✅" if test.status == TestStatus.PASSED else "❌" for test in result.tests)
    print(f"--- graded ({args.sandbox}): code found as {record.extract_method} ---")
    print(f"Status: {result.status}   Reward: {result.reward} ({result.passed}/{result.total})")
    if marks:
        print(f"Tests:  {marks}")
    if result.compile_error or result.error:
        print(f"Error:  {result.compile_error or result.error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
