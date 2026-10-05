// Ask the API about a job (a submission or a hint) until it is done or failed. Shared by the
// editor's submit and the hint panel.
//
// Each request waits for the previous answer, then 1 s (no setInterval pile-up when the API is
// slow). The caller passes `isCurrent`: when a newer poll starts, the user changes or the page
// closes, it returns false and this loop stops quietly at its next step.
import type { JobStatus } from "./types";

export const POLL_INTERVAL_MS = 1000;

export type PollEnd = "finished" | "stopped" | "timeout";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function pollUntilFinished<T extends { job_status: JobStatus }>(
  fetchOnce: () => Promise<T>,
  onUpdate: (value: T) => void,
  isCurrent: () => boolean,
  maxWaitMs: number,
): Promise<PollEnd> {
  const deadline = Date.now() + maxWaitMs;
  while (isCurrent()) {
    const value = await fetchOnce(); // an error goes to the caller
    if (!isCurrent()) return "stopped";
    onUpdate(value);
    if (value.job_status === "done" || value.job_status === "failed") return "finished";
    if (Date.now() > deadline) return "timeout";
    await sleep(POLL_INTERVAL_MS);
  }
  return "stopped";
}
