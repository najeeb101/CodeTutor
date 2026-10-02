# Week 2: eval harness (LLMs through the grader)

Written by Najeeb, reviewed by Claude.

<!--
HOW TO USE THIS FILE (delete this box when you are done)
- Each section has a grey box like this one with raw facts from Claude. They are notes, not text.
  Write your own sentences under the box. Use your own words: in an interview you can only
  say what you really understand.
- You don't have to use every fact. Choosing what matters is part of the exercise.
- When you are done, say "review". Claude checks every claim and number, marks each section
  ✅ / ⚠️ / ❌, and does not rewrite your text. Then these boxes are removed.
-->

## 1. What we built

<!--
Raw facts (pick 3-5 bullets, say what each part DOES, not only its name):
- Prompt: the model gets the STUDENT view only (description, starter code, visible tests; no
  solution, hints or hidden tests). build_messages() takes a StudentProblem, so the type itself
  blocks leaks. The text is pinned by a test: changing it needs a PROMPT_VERSION bump.
  src/codetutor/evals/prompt.py
- Code extraction: finds the code in a chatty reply (last block that defines the function, else
  the last python block, ...) and records HOW it was found, so "bad format" is counted apart
  from "wrong code". evals/extract.py
- pass@k with the unbiased estimator (Chen et al. 2021), from n = 10 answers per problem.
  evals/passk.py
- Model client: one small client (standard library only) for Ollama and Gemini, both via the
  OpenAI chat format. Failures are sorted: retry (429, 5xx, timeout, finish_reason "error"),
  stop for today (daily quota), stop at once (wrong key/model, server not running).
  evals/clients.py
- Run harness: one config file = one run = one append-only results file (one graded answer per
  line) + a meta file (versions, git commit, model digest). Resumable after a crash or a quota
  stop. Model code is graded in the Docker sandbox. evals/run.py, scripts/run_eval.py
- Metrics + report: pass@1 with a 95% bootstrap interval, pass@5/10, mean reward, results by
  module / difficulty / concept, failure types, hidden-only failures, hardest problems. Same
  results -> byte-identical report. evals/metrics.py, evals/report.py,
  lab/evals/reports/week2.md
- scripts/check_secrets.py: run before every commit; it fails if any real value from .env is in
  the staged changes (and never prints the value).
- 2 official runs: Qwen2.5-Coder 1.5B (fp16) and 7B (4-bit), 330 answers each.
-->

## 2. Key design decisions and trade-offs

<!--
Raw facts: pick 4-5. For each one say: the decision, WHY, and what it COSTS.

- Own client instead of LiteLLM (the brief said LiteLLM).
    why: both providers speak the same OpenAI format, so one ~300-line file is enough; LiteLLM would
    bring 58 packages in total instead of ~15 (measured), and two of its PyPI releases
    (1.82.7-1.82.8) were compromised in March 2026.  cost: we maintain the retry/error logic
    ourselves; no built-in cost tracking; a new provider needs a few lines.
- Prompt = student view only, pinned by a test.
    why: no hidden test or solution can leak; the model sees exactly what a student sees.
    cost: the model gets no hints; every prompt change needs a version bump and a new run.
- Extraction picks the last block that defines the function.
    why: small models often add a usage block (print(...)) after the solution.
    cost: it is a heuristic and can pick the wrong block, so format failures are counted
    separately (0 in both official runs).
- Unbiased pass@k from n = 10 answers per problem.
    why: much less noise than "did the first k answers pass?".  cost: 330 model calls per model.
- Seed i for answer i, temperature 0.8, model calls one at a time in a fixed order.
    why: a run can be repeated: re-asked seeded answers came back byte-identical (1.5B: 4/4,
    7B: 3/3, measured 2026-10-01).  cost: slower than parallel calls; only Ollama accepts a
    seed (Gemini answers HTTP 400 "Unknown name seed").
- Results are append-only JSONL + a meta file; a resume with different settings is refused.
    why: a run stopped by a quota continues later, and every number can be traced to its exact
    model weights, prompt, grader and commit.  cost: any change needs a new run_id and a new run.
- A failed API call is never graded.
    why: a server problem is not a model mistake; counting it would push pass@k down.
    cost: a run can stop "partial" and needs a rerun.
- Model code is graded in Docker.
    why: model-written code is untrusted.  cost: ~1 s extra per answer (~12x, measured with
    scripts/bench_sandbox.py).
- 95% interval = bootstrap over the 33 problems (2000 resamples, seed 0).
    why: honest error bars on a small bank.  cost: it ignores the noise from having only 10
    answers per problem (the report says so).
- Comparison model = local Qwen 7B (4-bit), not Gemini.
    why: free, unlimited, seedable, and the same family as the Week 6-7 training model.
    cost: it changes two things at once (size AND precision: 4-bit vs fp16). Named in the report.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
Raw facts: pick ONE and tell it as a story: what we saw -> what we measured -> the cause ->
the fix -> what we learned. All are true and measured.

- finish_reason "error": on OpenRouter's free tier, 2 replies came back as HTTP 200 with empty
  content and finish_reason "error" (the provider failed mid-answer). Our client trusted the
  200, so the empty code was graded as compile_error: a server failure counted as a model
  mistake. Fix (test first): treat it like a 503 (retry, then a failed call, never graded).
  Lesson: HTTP 200 is not success; check the payload.
- Gemini's real free limit was 20 requests/day, not the 100-250 we expected. The official n = 5
  run stopped cleanly on the daily quota after 17 answers (plus 3 test calls that day = 20).
  The harness design worked: nothing was lost, and a rerun would continue. We changed Gemini
  to n = 1 (33 calls, 2 days).
- Qwen crashed on the GPU: Ollama 0.35.0's CUDA build did not work with NVIDIA driver 546.18.
  Updating the driver to 617.14 fixed it (first call 11.7 s to load the model, then 2-3 s).
- group_anagrams: both models pass only 2/10, and the test they fail most is the VISIBLE
  example 1 (8 times each), which is right there in the prompt. Both do the two sort steps in
  the wrong order: they sort the groups before sorting the words inside each group. A model
  that could run the visible tests would see its mistake.
- word_frequency (1.5B 2/10, 7B 1/10): the spec says characters inside a word stay ("don't").
  5 of the 7B's 9 failures use a letters-only regex like \w+, which splits "don't" into "don"
  and "t": they solve the familiar task, not the one asked.
- The report printed the same true value (Dictionaries, 23/40 = 0.575) as 0.58 for one model
  and 0.57 for the other (float noise + Python's round-half-even). Found by re-computing odd
  cells with exact fractions. Fix: one formatter, round half up.
-->

## 4. Numbers

Measured by Claude on 2026-10-02 (from the committed results and today's runs), except where a
date says otherwise. Najeeb: check them before an interview.

| What | Qwen2.5-Coder 1.5B (fp16) | Qwen2.5-Coder 7B (4-bit) |
|---|---|---|
| Answers | 330 (33 problems × 10), 0 failed calls | 330, 0 failed calls |
| pass@1 [95% interval] | 0.867 [0.779, 0.942] | 0.945 [0.867, 1.000] |
| pass@5 / pass@10 | 0.983 / 1.000 | 0.978 / 1.000 |
| Mean reward (partial credit) | 0.953 | 0.989 |
| Wrong answers (of them hidden-only) | 44 (15) | 18 (9) |
| Failure types | 36 wrong_answer, 6 runtime_error, 2 compile_error | 18 wrong_answer |
| Weakest | group_anagrams 2/10, word_frequency 2/10, letter_grade 3/10 | word_frequency 1/10, group_anagrams 2/10 |
| Median time per answer | 1.8 s | 2.0 s |
| Whole run (model calls + Docker grading) | ~15 min | ~15 min |
| Re-asked seeded answers byte-identical (2026-10-01) | 4/4 | 3/3 |

| Project | Number |
|---|---|
| Hardware / cost | laptop RTX 4060 (8 GB), Ollama; $0 |
| pytest | 301 tests (+32 Docker-only tests), ~29-41 s depending on machine load |
| Eval code | ~1,600 lines in `src/codetutor/evals/`, ~1,170 lines of tests, ~350 lines of scripts |
| Grader version / prompt version | 0.2.1 / 1 |
| Time | 2 days (2026-10-01 → 2026-10-02); 22 commits before this wrap-up |

## 5. How I'd explain this in 60 seconds

<!--
No facts from Claude here, on purpose. Write it yourself, about 150 words, then say it out loud
without reading. Tip: what you measured, how you made it trustworthy, one surprising result,
and why it matters for Weeks 6-7 (GRPO).
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
Raw keywords (pick 3-4, and say WHY each one matters):
- Contamination: problems like fizzbuzz are all over the internet, so a model may remember them.
  A private, never-published held-out set (or freshly generated problems) measures real skill.
- Paired statistics: both models answer the same problems, so compare them problem by problem
  (paired bootstrap), not with two separate intervals.
- More prompts and temperatures: one prompt version and one temperature is one point of view.
- Let the model run the visible tests and retry (an agent loop): it would likely fix
  group_anagrams, which fails on a test the model can see.
- Parallel model calls and many grading workers (the Week 3 queue) for big models and banks.
- Cost and token tracking per run (needed for paid APIs).
- Per-test difficulty: which tests separate strong from weak models (item response theory).
- LLM-written problems, with the validator and buggy solutions as the quality gate.
-->

## 7. Five likely interview questions (and my answers)

<!-- The questions are Claude's (playing the interviewer). The answers are yours: 3-5 sentences
each, with one concrete example from this project. -->

**1. What is pass@k, and why use the unbiased estimator instead of "solved within the first k answers"?**

**2. How do you keep infrastructure failures out of a model's score?**

**3. Your 7B scores 0.945 and your 1.5B 0.867. How sure are you that the 7B is better, and what else is different between the two runs?**

**4. What is a hidden-only failure, and why does it matter for RL training?**

**5. How would someone reproduce one of your numbers exactly?**
