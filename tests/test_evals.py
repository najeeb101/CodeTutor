"""Tests for the offline eval core: pass@k, code extraction, prompts, records and fake models."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import pytest
from pydantic import JsonValue

from codetutor.evals import (
    FAKE_MODELS,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    EvalRecord,
    EvalRecordError,
    ExtractMethod,
    append_records,
    build_messages,
    extract_code,
    pass_at_k,
    read_records,
    score_reply,
)
from codetutor.evals.fake_models import oracle
from codetutor.evals.prompt import build_user_prompt
from codetutor.grader import GRADER_VERSION
from codetutor.problems import Problem, load_all
from conftest import valid_problem_data


@pytest.fixture(scope="module")
def bank() -> list[Problem]:
    """All problems in the bank."""
    return load_all()


@pytest.fixture(scope="module")
def sum_problem() -> Problem:
    """The small test problem from conftest (sum_of_evens)."""
    return Problem.model_validate(valid_problem_data())


def _call_text(function_name: str, args: list[JsonValue]) -> str:
    return f"{function_name}({', '.join(repr(arg) for arg in args)})"


# --- pass@k ---


def _brute_force_pass_at_k(n: int, c: int, k: int) -> float:
    """Try every way to pick k of the n samples (the first c pass); count the picks with a pass."""
    picks = list(combinations(range(n), k))
    with_a_pass = sum(1 for pick in picks if any(index < c for index in pick))
    return with_a_pass / len(picks)


def _binomial(n: int, c: int, p: float) -> float:
    """The chance of exactly c passes in n samples when each passes with chance p."""
    return math.comb(n, c) * p**c * (1 - p) ** (n - c)


def test_pass_at_k_matches_brute_force() -> None:
    for n in range(1, 9):
        for c in range(n + 1):
            for k in range(1, n + 1):
                expected = _brute_force_pass_at_k(n, c, k)
                assert pass_at_k(n, c, k) == pytest.approx(expected), (n, c, k)


@pytest.mark.parametrize(
    ("n", "c", "k"), [(200, 37, 10), (200, 1, 100), (1000, 3, 1), (100, 0, 50)]
)
def test_pass_at_k_large_n_matches_exact_fractions(n: int, c: int, k: int) -> None:
    exact = 1 - Fraction(math.comb(n - c, k), math.comb(n, k))
    assert pass_at_k(n, c, k) == pytest.approx(float(exact), rel=1e-12, abs=1e-15)


@pytest.mark.parametrize(
    ("n", "c", "k", "expected"),
    [
        (10, 3, 1, 0.3),  # pass@1 is simply the fraction that passed
        (5, 0, 1, 0.0),
        (5, 0, 5, 0.0),
        (5, 5, 1, 1.0),
        (5, 3, 3, 1.0),  # only 2 failing samples, so any 3 include a pass
    ],
)
def test_pass_at_k_simple_cases(n: int, c: int, k: int, expected: float) -> None:
    assert pass_at_k(n, c, k) == pytest.approx(expected)


@pytest.mark.parametrize(("n", "c", "k"), [(5, 0, 0), (5, 0, 6), (5, 6, 1), (5, -1, 1), (0, 0, 1)])
def test_pass_at_k_rejects_impossible_inputs(n: int, c: int, k: int) -> None:
    with pytest.raises(ValueError):
        pass_at_k(n, c, k)


def test_estimator_is_unbiased() -> None:
    """Averaged over every possible outcome, the estimate equals the true pass@k, 1 - (1 - p)^k."""
    for p in (0.1, 0.5, 0.9):
        for n in (2, 5, 10):
            for k in range(1, n + 1):
                average = sum(_binomial(n, c, p) * pass_at_k(n, c, k) for c in range(n + 1))
                assert average == pytest.approx(1 - (1 - p) ** k), (p, n, k)


def test_naive_estimate_is_biased() -> None:
    """The naive 1 - (1 - c/n)^k is too low on average: 0.625 instead of 0.75 here."""
    n, k, p = 2, 2, 0.5
    naive = sum(_binomial(n, c, p) * (1 - (1 - c / n) ** k) for c in range(n + 1))
    assert 1 - (1 - p) ** k == pytest.approx(0.75)
    assert naive == pytest.approx(0.625)


# --- code extraction (function name "f") ---

F_N = "def f(n):\n    return n\n"
PY = ExtractMethod.PYTHON_BLOCK
OTHER = ExtractMethod.OTHER_BLOCK

EXTRACTION_CASES = [
    pytest.param("```python\ndef f(n):\n    return n\n```", PY, F_N, id="python_block"),
    pytest.param(
        "Here you go:\n\n```python\ndef f(n):\n    return n\n```\n\nIt returns n.",
        PY,
        F_N,
        id="prose",
    ),
    pytest.param(
        "Draft:\n```python\ndef f(n):\n    pass\n```\n"
        "Final:\n```python\ndef f(n):\n    return n\n```\n"
        "Usage:\n```python\nprint(f(3))\n```",
        PY,
        F_N,
        id="draft_final_usage",
    ),
    pytest.param("def f(n):\n    return n\n", ExtractMethod.RAW, F_N, id="no_fence"),
    pytest.param(
        "The answer is to return n.",
        ExtractMethod.RAW,
        "The answer is to return n.\n",
        id="prose_only",
    ),
    pytest.param("```\ndef f(n):\n    return n\n```", OTHER, F_N, id="untagged_block"),
    pytest.param("```Python\ndef f(n):\n    return n\n```", PY, F_N, id="tag_upper_case"),
    pytest.param("```py\ndef f(n):\n    return n\n```", PY, F_N, id="tag_py"),
    pytest.param(
        "<think>\n```python\ndef f(n):\n    return 0\n```\n</think>\n```python\ndef f(n):\n"
        "    return n\n```",
        PY,
        F_N,
        id="think_is_dropped",
    ),
    pytest.param(
        "<think>I need a loop ```python\ndef f(", ExtractMethod.EMPTY, "", id="unclosed_think"
    ),
    pytest.param("```python\r\ndef f(n):\r\n    return n\r\n```\r\n", PY, F_N, id="crlf"),
    pytest.param("Here:\n```python\ndef f(n):\n    return n", PY, F_N, id="cut_off_block"),
    pytest.param(
        "1. Code:\n   ```python\n   def f(n):\n       return n\n   ```\n", PY, F_N, id="indented"
    ),
    pytest.param("", ExtractMethod.EMPTY, "", id="empty_reply"),
    pytest.param("  \n\t\n", ExtractMethod.EMPTY, "", id="whitespace_only"),
    pytest.param("```python\n```", ExtractMethod.EMPTY, "", id="empty_block"),
    pytest.param(
        "```python\ndef g(n):\n    return n\n```\nOutput:\n```text\n5\n```",
        PY,
        "def g(n):\n    return n\n",
        id="python_beats_later_text_block",
    ),
    pytest.param(
        "```text\n[1, 2]\n```\n```bash\npython x.py\n```", OTHER, "python x.py\n", id="last_block"
    ),
    pytest.param(
        "```python\ndef f(n):\n    return n\n```\n```python\ndef ff(n):\n    return 2\n```",
        PY,
        F_N,
        id="similar_name_is_not_the_function",
    ),
]


@pytest.mark.parametrize(("reply", "method", "code"), EXTRACTION_CASES)
def test_extract_code(reply: str, method: ExtractMethod, code: str) -> None:
    extraction = extract_code(reply, "f")
    assert extraction.method == method
    assert extraction.code == code


# --- prompts ---

PINNED_PROMPT = '''## Sum of Even Numbers

Return the sum of the even numbers from 1 to n.

### Visible tests
    sum_of_evens(10) -> 30
    sum_of_evens(7) -> 12
    sum_of_evens(2) -> 2
    sum_of_evens(1) -> 0

### Starter code
```python
def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    pass
```

### Rules
- Write the function `sum_of_evens` in Python 3, with the same parameters as the starter code.
- Return the answer. Do not print it, and do not use input().
- Use only the Python standard library.
- Hidden tests check more cases than the visible ones, so handle everything the description says.
- Reply with the complete function in one ```python code block.
'''


def test_prompt_text_is_pinned(sum_problem: Problem) -> None:
    """Scores from different prompts can't be compared, so a text change needs a new version."""
    messages = build_messages(sum_problem.to_student_view())
    assert [message["role"] for message in messages] == ["system", "user"]
    changed = "the prompt text changed: bump PROMPT_VERSION, then update PINNED_PROMPT"
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"] == PINNED_PROMPT, changed
    assert PROMPT_VERSION == "1", "PROMPT_VERSION changed: check PINNED_PROMPT too"


def test_prompt_shows_what_a_student_sees(bank: list[Problem]) -> None:
    for problem in bank:
        prompt = build_user_prompt(problem.to_student_view())
        assert problem.description_en.strip() in prompt, problem.id
        assert problem.starter_code.strip() in prompt, problem.id
        for test in problem.visible_tests:
            assert _call_text(problem.function_name, test.input) in prompt, (problem.id, test.id)


def test_prompt_never_shows_hidden_material(bank: list[Problem]) -> None:
    for problem in bank:
        messages = build_messages(problem.to_student_view())
        text = "\n".join(message["content"] for message in messages)
        assert problem.solution_code.strip() not in text, problem.id
        for name, code in problem.buggy.items():
            assert code.strip() not in text, (problem.id, name)
        for hint in problem.hints:
            assert hint not in text, problem.id
        visible_calls = {_call_text(problem.function_name, t.input) for t in problem.visible_tests}
        for test in problem.hidden_tests:
            call = _call_text(problem.function_name, test.input)
            # A few descriptions state an edge case on purpose, e.g. gcd(0, 0) and
            # two_sum([3, 3], 6). That is the author's choice, not a leak by the prompt.
            if call in visible_calls or call in problem.description_en:
                continue
            assert call not in text, (problem.id, test.id)


def test_input_rule_only_where_the_problem_checks_it(bank: list[Problem]) -> None:
    for problem in bank:
        prompt = build_user_prompt(problem.to_student_view())
        has_rule = "Do not change the arguments" in prompt
        assert has_rule == problem.check_input_unchanged, problem.id


# --- records ---


def _oracle_record(problem: Problem, sample_index: int) -> EvalRecord:
    reply = oracle(problem)
    return score_reply(
        problem, reply, model="fake/oracle", temperature=0.0, sample_index=sample_index
    )


def test_records_round_trip_through_jsonl(sum_problem: Problem, tmp_path: Path) -> None:
    records = [_oracle_record(sum_problem, index) for index in range(3)]
    path = tmp_path / "results.jsonl"
    append_records(path, records[:1])
    append_records(path, records[1:])  # appends, never overwrites
    assert read_records(path) == records


def test_bad_record_line_names_the_line(sum_problem: Problem, tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    good_line = _oracle_record(sum_problem, 0).model_dump_json()
    path.write_text(good_line + "\n\n" + '{"model": "x"}\n', encoding="utf-8")
    with pytest.raises(EvalRecordError, match="line 3"):
        read_records(path)


# --- end to end with fake models (no network) ---


def _score_bank(bank: list[Problem], model: str) -> list[EvalRecord]:
    """One sample per problem from a fake model, graded 4 at a time (like the validator)."""
    fake = FAKE_MODELS[model]

    def one(problem: Problem) -> EvalRecord:
        return score_reply(problem, fake(problem), model=model, temperature=0.0, sample_index=0)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, bank))


def test_oracle_gets_full_marks_on_every_problem(bank: list[Problem]) -> None:
    records = _score_bank(bank, "fake/oracle")
    assert [(r.problem_id, r.result.status) for r in records if not r.passed] == []
    assert {r.result.reward for r in records} == {1.0}
    pass_at_1 = sum(pass_at_k(1, int(r.passed), 1) for r in records) / len(records)
    assert pass_at_1 == 1.0
    assert {(r.prompt_version, r.result.grader_version) for r in records} == {
        (PROMPT_VERSION, GRADER_VERSION)
    }


def test_chatty_replies_are_extracted_right_on_every_problem(bank: list[Problem]) -> None:
    records = _score_bank(bank, "fake/chatty")
    assert [r.problem_id for r in records if not r.passed] == []
    assert {r.extract_method for r in records} == {ExtractMethod.PYTHON_BLOCK}


@pytest.mark.parametrize("model", ["fake/starter", "fake/buggy"])
def test_starter_and_buggy_are_never_accepted(bank: list[Problem], model: str) -> None:
    records = _score_bank(bank, model)
    assert [r.problem_id for r in records if r.passed] == []
    # Not "reward 0": the starter returns None, the right answer for some second_largest tests.
