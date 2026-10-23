"""Hugging Face generation for the baseline and the "after" eval (Week 6 Step 3).

The Week 2 run harness asks for one (problem, sample) at a time. A GPU decodes 10 answers about
as fast as 1 (docs/rl.md §1), so `BatchedResponder` generates **all n answers of a problem at the
first request** and serves the rest from a cache. `HFGenerator` does the real work and imports
torch only when it is used; the cache logic works (and is tested) with any generator function.

Sampling is plain: temperature only (no top-p, no top-k, no repetition penalty), so "before" and
"after" training use the same, known distribution.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from codetutor.evals.records import ModelReply
from codetutor.problems import Problem

HF_SEED = 0  # set before every batch: the same machine and software give the same answers

# (chat messages, n, seed offset) -> n replies; the batch seed is HF_SEED + offset
Generate = Callable[[list[dict[str, str]], int, int], list[ModelReply]]


class BatchRequestError(ValueError):
    """The harness asked for a sample the batch does not have."""


class BatchedResponder:
    """A harness `Responder` that generates all n samples of a problem in one go."""

    def __init__(self, generate: Generate, samples: int, seed_base: int = 0) -> None:
        self._generate = generate
        self._samples = samples
        self._seed_base = seed_base
        self._cache: tuple[str, list[ModelReply]] | None = None

    def __call__(
        self, problem: Problem, messages: list[dict[str, str]], seed: int | None
    ) -> ModelReply:
        """Sample number `seed - seed_base` of `problem`.

        The harness has no "sample index" argument, but it passes `seed_base + index` as the
        seed, so the position in the batch is `seed - seed_base`. With `seed_base: 0` (all
        official runs so far) the record's `seed` field is that position and the batch is made
        with `HF_SEED`; a larger `seed_base` shifts the batch seed to `HF_SEED + seed_base`, which
        gives a different but still repeatable draw of answers (Week 7: how big is eval luck?).
        Asking for a sample that was saved already is the harness's business: it never does.
        """
        if seed is None:
            raise BatchRequestError("hf runs need a seed (set `seed_base` in the config)")
        position = seed - self._seed_base
        if not 0 <= position < self._samples:
            raise BatchRequestError(
                f"{problem.id}: sample {position} of a batch of {self._samples}"
            )
        if self._cache is None or self._cache[0] != problem.id:
            self._cache = (
                problem.id,
                self._generate(messages, self._samples, self._seed_base),
            )
        return self._cache[1][position]


class HFGenerator:
    """A model loaded on the GPU that answers chat messages, n answers at a time."""

    def __init__(
        self, model_id: str, temperature: float, max_new_tokens: int, adapter: str | None = None
    ) -> None:
        import torch
        import transformers

        self._torch = torch
        self.adapter = adapter
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens
        self.dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        self.tokenizer = transformers.AutoTokenizer.from_pretrained(model_id, padding_side="left")
        self.model = transformers.AutoModelForCausalLM.from_pretrained(
            model_id, dtype=self.dtype
        ).to("cuda")
        if adapter is not None:  # a LoRA adapter from training (Week 7)
            from peft import PeftModel

            self.model = PeftModel.from_pretrained(self.model, adapter).to("cuda")
        self.model.eval()

    def __call__(
        self, messages: list[dict[str, str]], n: int, seed_offset: int = 0
    ) -> list[ModelReply]:
        torch = self._torch
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer([prompt], return_tensors="pt").to("cuda")
        torch.manual_seed(HF_SEED + seed_offset)
        start = time.perf_counter()
        with torch.no_grad():
            output = self.model.generate(
                **inputs,
                do_sample=True,
                temperature=self.temperature,
                top_p=1.0,
                top_k=0,
                repetition_penalty=1.0,
                max_new_tokens=self.max_new_tokens,
                num_return_sequences=n,
                pad_token_id=self.tokenizer.pad_token_id,
            )
        latency_ms = (time.perf_counter() - start) * 1000
        prompt_tokens = int(inputs["input_ids"].shape[1])
        ends = {self.tokenizer.eos_token_id, self.tokenizer.pad_token_id}
        replies = []
        for row in output[:, prompt_tokens:]:
            tokens = row.tolist()
            length = next((i for i, t in enumerate(tokens) if t in ends), len(tokens))
            finished = length < len(tokens)
            replies.append(
                ModelReply(
                    text=self.tokenizer.decode(tokens[:length], skip_special_tokens=True),
                    latency_ms=latency_ms,  # the whole batch: the answers were made together
                    prompt_tokens=prompt_tokens,
                    completion_tokens=length,
                    total_tokens=prompt_tokens + length,
                    finish_reason="stop" if finished else "length",
                )
            )
        return replies

    def details(self) -> dict[str, Any]:
        """What identifies this generator, for the run's meta file."""
        import transformers

        torch = self._torch
        extra: dict[str, Any] = {}
        if self.adapter is not None:  # which trained weights were tested
            weights = Path(self.adapter) / "adapter_model.safetensors"
            extra["adapter"] = str(self.adapter)
            extra["adapter_sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
        return {
            **extra,
            "runtime": "huggingface-transformers",
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "dtype": str(self.dtype).removeprefix("torch."),
            "device": torch.cuda.get_device_name(0),
            "seed": HF_SEED,
            "sampling": "temperature only (top_p 1.0, top_k off, repetition_penalty 1.0)",
        }
