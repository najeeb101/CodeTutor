"""The training-environment helpers (Week 6 Step 0). They need no GPU and no `rl` packages."""

from __future__ import annotations

from codetutor.rl.env import MIN_FREE_VRAM_GB, OllamaModel, parse_ollama_ps, vram_verdict

HEADER = "NAME    ID    SIZE    PROCESSOR    CONTEXT    UNTIL\n"
LOADED = HEADER + (
    "qwen2.5-coder:7b    dae161e27b0e    5.2 GB    100% GPU    4096    4 minutes from now\n"
    "nomic-embed-text:latest    0a109f422b47    634 MB    100% GPU    2048    4 minutes from now\n"
)


def test_an_idle_ollama_has_no_models() -> None:
    assert parse_ollama_ps(HEADER) == []
    assert parse_ollama_ps("") == []


def test_loaded_models_are_read_with_their_two_word_size() -> None:
    assert parse_ollama_ps(LOADED) == [
        OllamaModel("qwen2.5-coder:7b", "5.2 GB"),
        OllamaModel("nomic-embed-text:latest", "634 MB"),
    ]


def test_the_verdict_names_each_problem_in_plain_words() -> None:
    assert vram_verdict(MIN_FREE_VRAM_GB + 0.1, []) == []
    assert vram_verdict(MIN_FREE_VRAM_GB + 0.1, None) == []  # Ollama not askable: no complaint
    low = vram_verdict(2.0, parse_ollama_ps(LOADED))
    assert len(low) == 2
    assert "qwen2.5-coder:7b" in low[0] and "2.0 GiB" in low[1]
