"use client";

// Shown when a page fails to render, usually because the API is not running. In a
// production build, errors from server components show only a generic message (Next.js hides
// the details), so the hint below is what helps.
export default function ErrorPage({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <div className="error-page">
      <h1>Something went wrong</h1>
      <p>{error.message}</p>
      <p>
        Is the API running? Start it with <code>make api</code>, and <code>make worker</code> to
        grade submissions.
      </p>
      {/* retry() fetches the page again; reset() would only re-render the old failure */}
      <button type="button" onClick={() => retry()}>
        Try again
      </button>
    </div>
  );
}
