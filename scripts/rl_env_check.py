"""Check that this machine can train (Week 6 Step 0): GPU, memory, model, grader.

Usage:
    make rl-env                                              # the 0.5B model
    uv run --group rl python scripts/rl_env_check.py --model Qwen/Qwen2.5-Coder-1.5B-Instruct

It prints the versions, the free GPU memory, whether Ollama still holds models, loads the model,
answers one problem (8 samples at once, as GRPO will), grades the first answer with the real
Docker grader, and reports memory and speed. Exit code 1 with a hint when something is wrong.
Nothing is saved.
"""

from __future__ import annotations

import argparse
import sys
import time

from codetutor.evals import build_messages, extract_code
from codetutor.grader import DockerSandbox, SandboxUnavailableError, grade
from codetutor.problems import get_problem
from codetutor.rl.env import DEFAULT_MODEL, GIB, loaded_ollama_models, vram_verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--problem", default="cs1.loops.fizzbuzz")
    parser.add_argument("--samples", type=int, default=8, help="answers generated at once")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    try:
        import torch
        import transformers
    except ImportError:
        print("The `rl` packages are missing: run `uv sync --group rl`.", file=sys.stderr)
        return 1
    if not torch.cuda.is_available():
        print(
            "torch can't see the GPU. In WSL, `nvidia-smi` must work; update the Windows NVIDIA "
            "driver if it does not.",
            file=sys.stderr,
        )
        return 1

    free_bytes, total_bytes = torch.cuda.mem_get_info()
    print(f"torch {torch.__version__}, transformers {transformers.__version__}")
    print(f"GPU: {torch.cuda.get_device_name(0)}, {total_bytes / GIB:.1f} GiB total")
    ollama = loaded_ollama_models()
    print(
        "Ollama: "
        + ("could not be asked" if ollama is None else ", ".join(m.name for m in ollama) or "idle")
    )
    problems = vram_verdict(free_bytes / GIB, ollama)
    print(f"free GPU memory before loading: {free_bytes / GIB:.1f} GiB")
    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)

    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    print(f"loading {args.model} in {str(dtype).removeprefix('torch.')} ...")
    start = time.perf_counter()
    try:
        tokenizer = transformers.AutoTokenizer.from_pretrained(args.model, padding_side="left")
        model = transformers.AutoModelForCausalLM.from_pretrained(args.model, dtype=dtype).to(
            "cuda"
        )
    except OSError as exc:
        print(
            f"Could not load the model (no internet for the first download?): {exc}",
            file=sys.stderr,
        )
        return 1
    parameters = sum(p.numel() for p in model.parameters())
    print(
        f"loaded in {time.perf_counter() - start:.1f} s: {parameters / 1e6:.0f}M parameters, "
        f"{torch.cuda.memory_allocated() / GIB:.2f} GiB of weights"
    )

    problem = get_problem(args.problem)
    messages = build_messages(problem.to_student_view())
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    with torch.no_grad():
        output = model.generate(
            **inputs,
            do_sample=True,
            temperature=0.8,
            max_new_tokens=args.max_new_tokens,
            num_return_sequences=args.samples,
            pad_token_id=tokenizer.pad_token_id,
        )
    seconds = time.perf_counter() - start
    answers = output[:, inputs["input_ids"].shape[1] :]
    new_tokens = int((answers != tokenizer.pad_token_id).sum())
    print(
        f"{args.samples} answers in {seconds:.1f} s: {new_tokens} new tokens "
        f"({new_tokens / seconds:.0f} tokens/s), peak GPU memory "
        f"{torch.cuda.max_memory_allocated() / GIB:.2f} GiB"
    )

    reply = tokenizer.decode(answers[0], skip_special_tokens=True)
    code = extract_code(reply, problem.function_name).code
    try:
        sandbox = DockerSandbox()
    except SandboxUnavailableError as exc:
        print(f"Docker is not available for grading: {exc}", file=sys.stderr)
        return 1
    start = time.perf_counter()
    result = grade(problem, code, reveal_hidden=False, sandbox=sandbox)
    print(
        f"first answer graded in Docker in {time.perf_counter() - start:.1f} s: "
        f"{result.status.value}, reward {result.reward} ({result.passed}/{result.total})"
    )
    print("--- first answer ---")
    print(reply.strip())
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
