"use client";

// Ask the AI tutor for a hint, read it, rate it 👍/👎 (docs/api.md, docs/tutor.md §4).
// The API only queues the request (202); the tutor worker writes the hint; this panel polls
// GET /api/hints/{id} like the editor polls a submission. Levels go in order: 1 (a nudge),
// 2 (more specific), then the teacher's last hint, which gives most of the answer.
import { useCallback, useEffect, useRef, useState } from "react";

import { InlineCode } from "@/components/InlineCode";
import { ApiError, apiFetch } from "@/lib/api";
import { pollUntilFinished } from "@/lib/poll";
import type { Hint, HintCreated, Problem, Submission } from "@/lib/types";
import { useUser } from "@/lib/user";

const MAX_WAIT_MS = 150_000; // a model that must load first took up to 109 s (after a reboot)
const SLOW_NOTE_AFTER_MS = 10_000;
const HINT_LIMIT = 20;
const MAX_QUESTION_CHARS = 500; // the API's limit

const LAST_HINT_WARNING =
  "The last hint is your teacher's own, and it gives away most of the answer. Show it?";

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  if (error.status === 429 && error.retryAfterS !== null) {
    return `${error.detail} (try again in ${error.retryAfterS} s)`;
  }
  return error.detail;
}

function sourceText(hint: Hint): string {
  if (hint.source === "model") return "from the AI tutor";
  return "from your teacher"; // fallback or reference: the problem's own hint
}

function upsert(hints: Hint[], hint: Hint): Hint[] {
  const others = hints.filter((item) => item.id !== hint.id);
  return [hint, ...others].sort((a, b) => b.id - a.id); // newest first
}

interface Props {
  problem: Problem;
  code: string; // the editor's code
  graded: Submission | null; // the shown submission, when the editor holds exactly its code
}

export function HintPanel({ problem, code, graded }: Props) {
  const { user, forget } = useUser();
  const [hints, setHints] = useState<Hint[]>([]);
  const [question, setQuestion] = useState("");
  const [waiting, setWaiting] = useState(false); // a request is queued or being answered
  const [slow, setSlow] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const pollGeneration = useRef(0); // see Workspace.tsx

  useEffect(() => () => void pollGeneration.current++, []); // stop polling on unmount

  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        forget();
        setMessage("Your session ended. Start again (top right).");
      } else {
        setMessage(errorText(error));
      }
    },
    [forget],
  );

  const follow = useCallback(
    async (hintId: number) => {
      const generation = ++pollGeneration.current;
      const isCurrent = () => pollGeneration.current === generation;
      setWaiting(true);
      setSlow(false);
      const slowTimer = setTimeout(() => isCurrent() && setSlow(true), SLOW_NOTE_AFTER_MS);
      try {
        const end = await pollUntilFinished(
          () => apiFetch<Hint>(`/api/hints/${hintId}`),
          (hint) => setHints((old) => upsert(old, hint)),
          isCurrent,
          MAX_WAIT_MS,
        );
        if (end === "timeout") setMessage("The tutor is taking very long. Look again in a minute.");
      } catch (error) {
        if (isCurrent()) handleError(error);
      } finally {
        clearTimeout(slowTimer);
        if (isCurrent()) {
          setWaiting(false);
          setSlow(false);
        }
      }
    },
    [handleError],
  );

  // On mount and when the user changes: forget the old user's hints, load this user's, and
  // keep following a request that is still waiting (e.g. after a page reload).
  useEffect(() => {
    pollGeneration.current++;
    setHints([]);
    setWaiting(false);
    setMessage(null);
    if (!user) return;
    const query = `problem_id=${encodeURIComponent(problem.id)}&limit=${HINT_LIMIT}`;
    apiFetch<Hint[]>(`/api/hints?${query}`)
      .then((loaded) => {
        setHints(loaded);
        const open = loaded.find((hint) => hint.job_status === "queued" || hint.job_status === "running");
        if (open) void follow(open.id);
      })
      .catch(handleError);
  }, [user, problem.id, follow, handleError]);

  async function ask(level: number) {
    if (!user) return;
    if (level === 3 && !window.confirm(LAST_HINT_WARNING)) return;
    setMessage(null);
    const about = graded ? { submission_id: graded.id } : { code };
    try {
      const created = await apiFetch<HintCreated>("/api/hints", {
        method: "POST",
        body: {
          problem_id: problem.id,
          problem_version: problem.version,
          level,
          question: question.trim() || null,
          ...about,
        },
      });
      setQuestion("");
      void follow(created.id);
    } catch (error) {
      handleError(error);
    }
  }

  async function rate(hint: Hint, rating: 1 | -1) {
    if (!user) return;
    try {
      const rated = await apiFetch<Hint>(`/api/hints/${hint.id}/rating`, {
        method: "PUT",
        body: { rating },
      });
      setHints((old) => upsert(old, rated));
    } catch (error) {
      handleError(error);
    }
  }

  const highest = Math.max(0, ...hints.filter((hint) => hint.job_status === "done").map((hint) => hint.level));
  const nextLevel = highest >= 1 ? 2 : 1;

  return (
    <section className="hints" aria-labelledby="hints-heading">
      <h2 id="hints-heading">Stuck? Ask the tutor</h2>
      {!user ? (
        <p className="muted">Start as a guest (top right) to ask for a hint.</p>
      ) : (
        <>
          <p className="muted">
            The tutor gives hints, not answers. It looks at{" "}
            {graded ? `your submission #${graded.id} and its test results` : "the code in the editor (not tested yet)"}.
          </p>
          <p className="muted">
            Hints are made by a small AI model running on this server. Your code is not sent to
            any other service.
          </p>
          <label className="question">
            Your question (optional)
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              maxLength={MAX_QUESTION_CHARS}
              rows={2}
              placeholder="e.g. Why does my loop stop too early?"
            />
          </label>
          <div className="actions">
            <button type="button" onClick={() => ask(nextLevel)} disabled={waiting}>
              {nextLevel === 1 ? "Get a hint" : "Get a more specific hint"}
            </button>
            {highest >= 2 && (
              <button type="button" onClick={() => ask(3)} disabled={waiting}>
                Show the last hint
              </button>
            )}
          </div>
        </>
      )}
      {waiting && (
        <p className="result pending" role="status">
          The tutor is thinking…
          {slow && " The first hint after a break can take up to 2 minutes."}
        </p>
      )}
      {message && (
        <p className="error" role="alert">
          {message}
        </p>
      )}
      <ol className="hint-list">
        {hints.map((hint) => (
          <HintItem key={hint.id} hint={hint} onRate={rate} />
        ))}
      </ol>
    </section>
  );
}

function HintItem({ hint, onRate }: { hint: Hint; onRate: (hint: Hint, rating: 1 | -1) => void }) {
  if (hint.job_status === "queued" || hint.job_status === "running") return null; // "thinking" above
  const label = hint.level === 3 ? "Last hint" : `Hint level ${hint.level}`;
  return (
    <li className="hint" data-hint-id={hint.id}>
      <p className="muted">
        {label} · {sourceText(hint)}
        {hint.question && <> · you asked: “{hint.question}”</>}
      </p>
      {hint.job_status === "failed" ? (
        <p className="error">{hint.message}</p>
      ) : (
        <>
          <p className="hint-text">
            <InlineCode text={hint.text ?? ""} />
          </p>
          <div className="rating">
            <span className="muted">Was this helpful?</span>
            <button
              type="button"
              aria-pressed={hint.rating === 1}
              aria-label="Helpful"
              onClick={() => onRate(hint, 1)}
            >
              👍
            </button>
            <button
              type="button"
              aria-pressed={hint.rating === -1}
              aria-label="Not helpful"
              onClick={() => onRate(hint, -1)}
            >
              👎
            </button>
          </div>
        </>
      )}
    </li>
  );
}
