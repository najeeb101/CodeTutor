"""Run the validator over the real problem bank inside pytest (brief 3.5).

Marked `slow` (deselected by default): it grades all 33 problems (~12 s), and `make all` runs
the same `validate_bank()` again through `make validate`. Run it with `uv run pytest -m slow`.
"""

from __future__ import annotations

import pytest

from codetutor.bank.validate import format_report, validate_bank


@pytest.mark.slow
def test_every_problem_in_the_bank_is_valid() -> None:
    bank = validate_bank()
    assert bank.problems, "no problems found under problems/"
    assert bank.valid, "\n" + format_report(bank)
