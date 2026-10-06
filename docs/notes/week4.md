# Week 4: the AI tutor (hints, not answers)

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
- A guardrail (tutor/guardrail.py): every hint is checked before a student sees it. It blocks
  fenced code, code statements (whole lines or `backtick` spans), and any non-trivial line of
  the reference solution (spaces removed, quotes unified). Text that is already in the starter
  code, the description or the student's own code is allowed.
- 8 course notes (course/notes/, one per module, 41 sections). Each `##` section is one search
  chunk, embedded with nomic-embed-text (768 numbers) into a pgvector column. Three search
  methods: keyword (Postgres full-text), vector (cosine distance), hybrid (both lists merged
  with reciprocal rank fusion). tutor/notes.py, tutor/rag.py
- The hint pipeline, `give_hint` (tutor/service.py): search the notes (top 3) → ask the model →
  guardrail + "not empty" + "max 80 words" → one retry → else the teacher's hint. Level 3 is
  always the teacher's last hint (no model).
- The trace: every hint request is a row in the `hints` table, with every attempt (blocked
  ones too), the notes found, the model, prompt version, time, tokens and the 👍/👎 rating.
- A tutor worker (`make tutor`): the `hints` row is also the job, claimed with FOR UPDATE SKIP
  LOCKED + a lease, like the grading queue. It keeps the 7B and the embedder loaded.
- 4 API endpoints (ask, get one, my hints, rate) and a hint panel in the UI (level 1 → 2 →
  last hint with a warning, 👍/👎, "from the AI tutor" / "from your teacher").
- Two measurements: a safety run (the tutor on all 97 buggy files + 10 prompt injections) and
  an offline eval (does a hint help a 1.5B "student" fix a hidden-only bug? graded by grade()).
-->

## 2. Key design decisions and trade-offs

<!--
Raw facts (pick 3-4; for each: the choice, the alternative, what it costs):
- The model never sees solution.py (only the problem, the teacher's hints up to the level,
  the student's code and visible results, hidden tests as counts). Cost: it can still write
  solution lines on its own (the 7B's pass@1 on the bank is 0.945), so the guardrail checks every
  hint against the solution anyway.
- Guardrail rule "anything that parses as Python is code" was REJECTED after measuring: it
  blocked 9 of 33 good hint 1s ("first: 2024" is a valid annotation, "return the" a return).
  Expressions like `number % 15 == 0` are allowed; statements like `count += 1` are not.
- Hybrid search chosen by measurement on 40 labelled questions: recall@3 keyword 34/40,
  vector 39/40, hybrid 40/40. Cost: two queries (~160-175 ms vs ~20 ms for keyword).
- 7B as the default tutor, not the 1.5B: the 1.5B's first try was blocked 49% (level 1) /
  29% (level 2), the 7B's 3% / 10%. A bigger model needs fewer fallbacks.
- A separate tutor worker instead of the API making hints: the hint needs the sealed problem
  copy (solution + teacher's hints) and the API never reads that table. Cost: one more process.
- Traces in Postgres, not Langfuse (a change from the brief): the table was needed anyway for
  ratings and later preference data; nothing leaves the machine. Cost: no ready-made trace UI.
- Our own model client, not LiteLLM (a change from the brief, decided in Week 2): ~50 fewer
  packages, and two LiteLLM releases were compromised in March 2026.
- Hint 3 is a "bottom-out" hint: 9 of the bank's hint 3s contain solution lines. Kept, shown
  only on request with a warning; the AI tutor is held to the strict rule.
- Prompts stay under 2,048 tokens (half of Ollama's default window), see section 3.
- The offline eval compares conditions *paired by situation* with a bootstrap interval.
-->

## 3. Hardest bug / surprise and how we fixed it

<!--
Raw facts (pick 1-2 and tell them as a story: what you saw, what you suspected, how you found
the cause, what you changed, how you proved the fix):
- Silent truncation: Ollama gives a model a 4,096-token window by default, and our
  OpenAI-style calls can't change it. Prompts of ~5,400 and ~18,000 tokens were cut to ~2,050
  tokens, keeping the END: the system message with the rules was gone, the model made up a
  code word, and the reported prompt size was BELOW the window. Fix: estimate chars / 3 before
  sending, stay under 2,048; a reported size >= 2,048 counts as "maybe cut".
- In a `json` column, Python None is saved as JSON `null`, which SQL sees as NOT NULL, so a
  CHECK ("a finished hint has its attempts") missed a missing value. Found by a test; fix:
  `JSON(none_as_null=True)`.
- Guardrail details found by tests: a solution line with a trailing comment never matched
  (fix: cut comments with `tokenize`); removing all spaces made `if need in seen:` look like
  one word (fix: compare trivial lines single-spaced).
- The tutor eval: a hint with the wrong diagnosis took group_anagrams from 0.80 to 0.00. The
  teacher's hint 1 lists three leads; the tutor picked "repeated words", the bug was repeated
  letters (`set(word)`).
- Ollama unloads a model 5 minutes after the last request; loading the 7B again took 12-13 s
  (109 s right after a reboot). Fix: the worker loads both models at start and refreshes them
  every 4 minutes.
- On battery the laptop is much slower: the test suite 60.5 s vs 45.3 s on mains (same day),
  a student answer 5.7 s vs ~2.4 s.
-->

## 4. Numbers

Measured by Claude between 2026-10-03 and 2026-10-06. Najeeb: check them before an interview.

| What | Number |
|---|---|
| Guardrail: bank hints 1-2 blocked / generated leaks blocked | 0 of 66 / 298 of 298 (+10 of 10 hand-written) |
| Note search recall@3 (40 questions): keyword / vector / hybrid | 34 / 39 / 40 |
| Search time per question: keyword / vector / hybrid | ~20 ms / ~120-155 ms / ~160-175 ms |
| Safety run, first try blocked, level 1 / 2: 7B / 1.5B | 3% / 10% vs 49% / 29% |
| Teacher's hint shown instead (7B), level 1 / 2 | 3% / 1% |
| Live hint, request → answer (warm 7B): level 1 / 2 / 3 | 3.8 s / 5.7 s / 0.8 s |
| Model reload after Ollama's idle unload / after a reboot | 12-13 s / 109 s |
| `make e2e` (11 checks) / `make web-e2e` (9 checks) | 19 s / 27 s |
| Tutor eval fix rate: no hint / teacher 1 / tutor 1 / tutor 2 / teacher 3 | 0.58 / 0.66 / 0.62 / 0.63 / 0.70 |
| Tutor eval help vs no hint: tutor 1 / tutor 2 | +0.04 [-0.02, +0.11] / +0.06 [-0.03, +0.15] |
| Tutor eval size and time | 54 situations × 6 conditions × 5 answers = 1,620 (1 failed call); 63 min for 1,350 |

| Project | Number |
|---|---|
| Database | 7 tables, 6 migrations (3 new: note_chunks, hints, hint jobs) |
| Packages | 0 new Python packages, 0 new npm packages (own pgvector column type) |
| pytest | 607 tests by default (+1 slow, +33 Docker-only); 191 of them new this week |
| Code this week (non-blank lines) | tutor/ 2,260, api/hints.py 151, migrations 214, web 263; tests 1,651 |
| Course notes | 8 notes, 41 sections, ~4,300 words |
| Time | 3 days (2026-10-03, 10-05, 10-06), 15 commits incl. this wrap-up and its status update |

## 5. How I'd explain this in 60 seconds

<!--
No facts from Claude here, on purpose. Write it yourself, about 150 words, then say it out loud
without reading. Tip: follow one hint request from the click to the screen, name the layers
that keep the answer out, and say honestly what the eval could and could not show.
-->

## 6. If I had more time / at Scale's scale, I would…

<!--
Raw keywords (pick 3-4, and say WHY each one matters):
- More eval data: n = 10 answers per situation, a second student model, real students'
  👍/👎 ratings; today the tutor's effect can't be told apart from 0.
- Tutor prompt v2 for the two failure cases ("the student" instead of "you" in 16 of 54
  level-2 hints; picking the wrong lead), measured with the same eval.
- A model as a second guardrail layer ("does this give the answer away?"), measured on the
  labelled hints first; rename-proof solution matching (`tally[w]` ≈ `counts[word]`).
- Use the 👍/👎 ratings as preference pairs for DPO (Week 6-7 option).
- At scale: a model server with batching (vLLM) instead of one Ollama on one GPU, more tutor
  workers on queue depth, a vector index (HNSW) once there are thousands of note sections.
- Tracing UI (Langfuse or similar) once real users exist, with consent for their code.
-->

## 7. Five likely interview questions (and my answers)

<!-- The questions are Claude's (playing the interviewer). The answers are yours: 3-5 sentences
each, with one concrete example from this project. -->

**1. How do you stop an LLM tutor from just giving the answer? Why isn't the prompt enough?**

**2. Why does the model never see the solution, and why do you still check every hint against it?**

**3. How did you choose between keyword, vector and hybrid search, and how much do you trust that result?**

**4. How do you know whether the tutor's hints actually help? What did you find, and what are the limits?**

**5. A hint request takes 2 minutes for the first student in the morning. Why, and what did you do about it?**
