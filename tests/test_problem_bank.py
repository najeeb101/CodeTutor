"""Run the validator over the real problem bank inside pytest (brief 3.5)."""

from __future__ import annotations

from codetutor.bank.validate import format_report, validate_bank


def test_every_problem_in_the_bank_is_valid() -> None:
    bank = validate_bank()
    assert bank.problems, "no problems found under problems/"
    assert bank.valid, "\n" + format_report(bank)
