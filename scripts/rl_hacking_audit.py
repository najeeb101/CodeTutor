"""Reward-hacking audit over the committed eval answers (Week 7 Step 3).

    uv run python scripts/rl_hacking_audit.py report   # lab/rl/reports/hacking.md (no GPU)
    uv run python scripts/rl_hacking_audit.py list     # print the flagged answers to read

Make target: `make rl-hacking`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from codetutor.evals.records import EvalRecord, read_records
from codetutor.problems import load_all
from codetutor.rl.hacking import audit_row, flagged_records, render_audit_report
from rl_after import BEFORE_FILE, POOL_DRAWS, POOL_FOLDS, REPO, RESULTS, after_file, draw_file

# fold c trained with a second seed is audited too
MODELS = {
    "untrained 0.5B": BEFORE_FILE,
    **{f"adapter {n}": after_file(n) for n in POOL_FOLDS},
    "adapter c (seed 1)": after_file("c-s1"),
}


def pooled_records(filename: str) -> list[EvalRecord]:
    """The answers of the three sampling draws of one model, draw 0 first."""
    records: list[EvalRecord] = []
    for draw in POOL_DRAWS:
        records.extend(read_records(RESULTS / draw_file(filename, draw)))
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["report", "list"])
    args = parser.parse_args()
    bank = {p.id: p for p in load_all()}
    if args.command == "report":
        rows = [audit_row(label, pooled_records(f), bank) for label, f in MODELS.items()]
        target = REPO / "lab" / "rl" / "reports" / "hacking.md"
        target.write_text(render_audit_report(rows), "utf-8")
        print(f"wrote {Path(target).relative_to(REPO)}")
        return 0
    for label, filename in MODELS.items():
        for record, found in flagged_records(pooled_records(filename), bank):
            print(
                f"##### {label} | {record.problem_id} #{record.sample_index} | "
                f"{record.result.status.value} | {','.join(found)}"
            )
            print(record.code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
