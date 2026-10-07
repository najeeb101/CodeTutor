"""Helpers for checking the training machine (Week 6 Step 0): GPU memory, Ollama, dtype.

No torch import at module level: these helpers also run (and are tested) without the `rl`
dependency group installed. `scripts/rl_env_check.py` is the command-line wrapper.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
MIN_FREE_VRAM_GB = 6.0  # below this, training the 0.5B with 8 samples per prompt gets tight
GIB = 1024**3


@dataclass(frozen=True)
class OllamaModel:
    """One row of `ollama ps`: a model that is loaded (and so holds GPU memory)."""

    name: str
    size: str


def parse_ollama_ps(output: str) -> list[OllamaModel]:
    """The loaded models in the text printed by `ollama ps` (empty list = nothing loaded).

    The first line is the header (NAME ID SIZE PROCESSOR CONTEXT UNTIL). The size is two
    words ("4.7 GB"), so the row is read by splitting on runs of 2+ spaces.
    """
    models = []
    for line in output.strip().splitlines()[1:]:
        columns = [part for part in line.split("  ") if part.strip()]
        if len(columns) >= 3:
            models.append(OllamaModel(columns[0].strip(), columns[2].strip()))
    return models


def loaded_ollama_models() -> list[OllamaModel] | None:
    """Ask the Windows Ollama what it holds in memory; None if it can't be asked."""
    exe = shutil.which("ollama.exe") or shutil.which("ollama")
    if exe is None:
        return None
    try:
        done = subprocess.run([exe, "ps"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_ollama_ps(done.stdout) if done.returncode == 0 else None


def vram_verdict(free_gib: float, ollama: list[OllamaModel] | None) -> list[str]:
    """Plain-English problems with the GPU memory, empty when it looks fine."""
    problems = []
    if ollama:
        names = ", ".join(m.name for m in ollama)
        problems.append(
            f"Ollama still holds models in memory ({names}). Wait ~10 minutes or restart "
            "Ollama, then run this again."
        )
    if free_gib < MIN_FREE_VRAM_GB:
        problems.append(
            f"Only {free_gib:.1f} GiB of GPU memory is free (want {MIN_FREE_VRAM_GB:.0f}+). "
            "Close browsers and other GPU programs on Windows, or stop Ollama."
        )
    return problems
