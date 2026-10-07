"""The "before" baseline for RL training (Week 6 Step 3).

Usage:
    make rl-baseline-run        # both official runs (~1 h of GPU; resumable)
    uv run python scripts/rl_baseline.py report        # lab/rl/reports/baseline.md

The runs use the Week 2 harness (resumable, graded in Docker, one results file each). `report`
needs no GPU: it reads the committed results.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codetutor.evals.metrics import load_run
from codetutor.problems import load_all
from codetutor.rl.baseline import NamedRun, render_report

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "lab" / "evals" / "results"
REPORT = REPO / "lab" / "rl" / "reports" / "baseline.md"
RUNS = {
    "0.5B (HF, bf16)": "hf-qwen2.5-coder-0.5b-bf16-t0.8-n10.jsonl",
    "1.5B (HF, bf16)": "hf-qwen2.5-coder-1.5b-bf16-t0.8-n10.jsonl",
}
CROSS_CHECK = ("1.5B (Ollama, fp16, Week 2)", "qwen2.5-coder-1.5b-fp16-t0.8-n10.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["report"])
    parser.parse_args()
    missing = [f for f in [*RUNS.values(), CROSS_CHECK[1]] if not (RESULTS / f).exists()]
    if missing:
        print(f"missing results: {', '.join(missing)} (see the usage above)", file=sys.stderr)
        return 1
    runs = [NamedRun(label, load_run(RESULTS / file)) for label, file in RUNS.items()]
    cross = NamedRun(CROSS_CHECK[0], load_run(RESULTS / CROSS_CHECK[1]))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_report(runs, load_all(), cross), encoding="utf-8")
    print(f"wrote {REPORT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
