"use client";

// The problem page's interactive part: editor, submit, polling for the result, and the
// student's earlier submissions for this problem. Grading happens in the worker; this
// component only asks the API (submit = 202, then poll GET /api/submissions/{id}).
import { useCallback, useEffect, useRef, useState } from "react";

import { CodeEditor } from "@/components/CodeEditor";
import { ResultView } from "@/components/ResultView";
import { HintPanel } from "@/components/HintPanel";
import { ApiError, apiFetch } from "@/lib/api";
import { pollUntilFinished } from "@/lib/poll";
import { readStored, writeStored } from "@/lib/storage";
import type { Problem, Submission, SubmissionCreated, SubmissionSummary } from "@/lib/types";
import { useUser } from "@/lib/user";

const MAX_WAIT_MS = 120_000; // the slowest bank problem needs ~38 s in Docker
const HISTORY_LIMIT = 10;

function draftKey(problemId: string): string {
  return `codetutor.draft.${problemId}`;
}

function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  if (error.status === 409) return `${error.detail}. Reload the page to get the new version.`;
  if (error.status === 429 && error.retryAfterS !== null) {
    return `${error.detail} (try again in ${error.retryAfterS} s)`;
  }
  return error.detail;
}

// The shown submission, if a hint can be about it: graded, on this problem version, and with
// exactly the code in the editor (else the hint is about the editor's code, not graded yet).
function gradedFor(current: Submission | null, code: string, problem: Problem): Submission | null {
  if (!current || current.job_status !== "done") return null;
  if (current.problem_version !== problem.version || current.code !== code) return null;
  return current;
}

export function Workspace({ problem }: { problem: Problem }) {
  const { user, logout } = useUser();
  const [code, setCode] = useState(problem.starter_code);
  const [sending, setSending] = useState(false);
  const [current, setCurrent] = useState<Submission | null>(null);
  const [history, setHistory] = useState<SubmissionSummary[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  // Each poll loop remembers the generation it started in. Starting a new poll, or leaving
  // the page, increments it, and the old loop stops at its next step.
  const pollGeneration = useRef(0);

  // The unsent draft (localStorage exists only in the browser, so read it after mounting).
  useEffect(() => {
    const draft = readStored(draftKey(problem.id));
    if (draft !== null) setCode(draft);
  }, [problem.id]);

  useEffect(() => () => void pollGeneration.current++, []); // stop polling on unmount

  function changeCode(next: string) {
    setCode(next);
    writeStored(draftKey(problem.id), next);
  }

  function resetCode() {
    setCode(problem.starter_code);
    writeStored(draftKey(problem.id), null);
  }

  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 401) {
        logout();
        setMessage("Please log in again (top right).");
      } else {
        setMessage(errorText(error));
      }
    },
    [logout],
  );

  const loadHistory = useCallback(async () => {
    if (!user) return;
    try {
      const query = `problem_id=${encodeURIComponent(problem.id)}&limit=${HISTORY_LIMIT}`;
      setHistory(await apiFetch<SubmissionSummary[]>(`/api/submissions?${query}`, { userId: user.id }));
    } catch (error) {
      handleError(error);
    }
  }, [user, problem.id, handleError]);

  // On mount and whenever the user changes (log in / log out): stop any running poll, forget
  // the old user's result, and load this user's submissions.
  useEffect(() => {
    pollGeneration.current++;
    setCurrent(null);
    setHistory([]);
    void loadHistory();
  }, [loadHistory]);

  // Ask for the result until it is done or failed (lib/poll.ts).
  const poll = useCallback(
    async (submissionId: number, userId: number) => {
      const generation = ++pollGeneration.current;
      const isCurrent = () => pollGeneration.current === generation;
      try {
        const end = await pollUntilFinished(
          () => apiFetch<Submission>(`/api/submissions/${submissionId}`, { userId }),
          setCurrent,
          isCurrent,
          MAX_WAIT_MS,
        );
        if (end === "finished") await loadHistory();
        if (end === "timeout") {
          setMessage("Still grading after 2 minutes. Look at your submissions below later.");
        }
      } catch (error) {
        if (isCurrent()) handleError(error);
      }
    },
    [loadHistory, handleError],
  );

  async function submit() {
    if (!user) {
      setMessage("Log in first (top right), then submit.");
      return;
    }
    setSending(true);
    setMessage(null);
    try {
      const created = await apiFetch<SubmissionCreated>("/api/submissions", {
        method: "POST",
        userId: user.id,
        body: { problem_id: problem.id, problem_version: problem.version, code },
      });
      setCurrent(null);
      void loadHistory();
      void poll(created.id, user.id);
    } catch (error) {
      handleError(error);
    } finally {
      setSending(false);
    }
  }

  function show(submissionId: number) {
    if (user) void poll(submissionId, user.id); // a done one is shown after one request
  }

  return (
    <section className="workspace">
      <CodeEditor value={code} onChange={changeCode} label={`Your code for ${problem.title}`} />
      <div className="actions">
        <button type="button" className="primary" onClick={submit} disabled={sending}>
          {sending ? "Sending…" : "Submit"}
        </button>
        <button type="button" onClick={resetCode}>
          Reset to starter code
        </button>
        {!user && <span className="muted">Log in to submit.</span>}
      </div>
      {message && (
        <p className="error" role="alert">
          {message}
        </p>
      )}
      {current && <ResultView submission={current} functionName={problem.function_name} />}
      <HintPanel problem={problem} code={code} graded={gradedFor(current, code, problem)} />

      {history.length > 0 && (
        <>
          <h2>Your submissions</h2>
          <ul className="history">
            {history.map((item) => (
              <li key={item.id}>
                <button type="button" className="link" onClick={() => show(item.id)}>
                  #{item.id}
                </button>{" "}
                {new Date(item.created_at).toLocaleString()} ·{" "}
                {item.result_status
                  ? `${item.result_status.replace("_", " ")} ${item.passed}/${item.total}`
                  : item.job_status}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
