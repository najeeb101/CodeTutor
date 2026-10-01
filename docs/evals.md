# Evals: running models through the grader

The eval harness asks language models to solve the problem bank and grades every answer with the
same `grade()` that grades students. This page covers setup and the model client (Week 2,
Step 2). The run harness and the report come in Steps 3–4.

## 1. Setup

### Ollama (local Qwen) from WSL
Ollama runs on Windows. By default it listens only on Windows' own `localhost`, which WSL (in
its default NAT mode) can't reach. **Mirrored networking** makes WSL share Windows' localhost:

1. Create `C:\Users\<you>\.wslconfig` with:
   ```
   [wsl2]
   networkingMode=mirrored
   ```
2. In PowerShell: `wsl --shutdown`, then reopen your terminal / VS Code.
3. Check from WSL: `curl http://localhost:11434/api/version`.

Don't set `OLLAMA_HOST=0.0.0.0` instead: that lets anyone on the same network (e.g. university
Wi-Fi) use your Ollama. If Ollama runs somewhere else, set `OLLAMA_BASE_URL`
(default `http://localhost:11434/v1`).

### The model
```
ollama pull qwen2.5-coder:1.5b-instruct-fp16
```
We use the **fp16** (full precision) version, not the default 4-bit one. Weeks 6–7 train the same
model with GRPO in full precision, so its score here is the fair "before training" number; 4-bit
rounding can move scores by a few points. ~3 GB, fits an 8 GB GPU.

### Gemini (free tier)
1. Google AI Studio → "Get API key", in a Google Cloud project **without billing**, so it can
   never cost money.
2. Copy `.env.example` to `.env` and fill in `GEMINI_API_KEY`. Git ignores `.env`; never commit
   it. A Gemini key is `AIza` plus 35 letters, digits, `-` or `_`. Before a commit, this must
   print 0 (it matches real keys only, not text like this line):
   `git diff --cached | grep -cE 'AIza[0-9A-Za-z_-]{35}'`
3. Run commands with `uv run --env-file .env ...` (no extra package needed).

Free-tier notes:
- Limits (requests per minute and per day) differ per model and per project, and Google changes
  them. Read yours at aistudio.google.com/rate-limit. Daily limits reset at midnight Pacific time.
- On the free tier Google may use prompts to improve its products. We only send the student view
  of a problem (public text: description, starter code, visible tests), never hidden tests or
  solutions.

## 2. Try one model on one problem
```
uv run --env-file .env python scripts/try_model.py ollama/qwen2.5-coder:1.5b-instruct-fp16 cs1.loops.fizzbuzz
uv run --env-file .env python scripts/try_model.py gemini/<model> cs1.loops.fizzbuzz --rpm 5
```
It prints the reply, the token counts, the latency, how the code was found, and the grade.
Options: `--temperature`, `--max-tokens`, `--seed`, `--show-prompt`, `--sandbox`. Grading uses
the **Docker sandbox by default**: model-written code is untrusted.

## 3. The model client (`src/codetutor/evals/clients.py`)
Ollama and Gemini both accept the OpenAI chat-completions format (`POST <base>/chat/completions`),
so one small client covers both. It uses only the standard library (`urllib`, `json`); we chose
not to add LiteLLM (~50 extra packages, and its PyPI releases 1.82.7–1.82.8 were compromised in
March 2026). Model specs look like `ollama/<model>` or `gemini/<model>`.

Every failure is sorted into one kind, because each needs a different reaction:

| What happened | Exception | What the client does |
|---|---|---|
| 429 (per minute), 500/502/503/504, timeout, dropped connection | (internal, transient) | Retry up to 4 times. Waits ~2, 4, 8, 16 s with jitter, or what the server asks (`Retry-After`, Gemini's `retryDelay`). Then `ModelError`. |
| 429 that names a per-day quota | `QuotaExhaustedError` | Stop at once: retrying today can't help. |
| 400/401/403/404 | `ModelConfigError` | Stop at once: wrong key, model name or parameter. |
| Connection refused, unknown host | `ModelUnavailableError` | Stop at once: the server isn't running or the address is wrong. |
| Reply isn't valid JSON / has no choices | `ModelError` | Stop with the start of the reply in the message. |

- **Throttle:** `--rpm N` keeps at least 60/N seconds between requests (thread-safe).
- **The key** goes only into the `Authorization` header. It is never in `repr`, error messages
  or records (and is blanked out if a server echoes it).
- **`finish_reason`** is kept in every reply: `"length"` means `max_tokens` cut the answer off.
  The report will count these apart from wrong code.
- **A failed call is never graded.** An infrastructure failure is not a model failure; counting
  it as a wrong answer would push pass@k down.

## 4. Known limitations
- The per-day quota is recognised by text ("per day" / "PerDay") in the 429 reply. If a provider
  words it differently, it is treated as per-minute and retried 4 times before failing.
- Whether `seed` makes replies repeatable depends on the provider (checked live in Step 2; see
  the Decisions log in CLAUDE.md).
- The client is synchronous. Parallel requests need threads; a single local GPU gains little from
  them anyway.
- Ollama's OpenAI endpoint uses Ollama's default context window. Our prompts are short, but a
  prompt longer than the window would be cut silently.
