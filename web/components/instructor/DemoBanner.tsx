import Link from "next/link";

// Shown on every demo page: visitors must never mistake this for real students.
export function DemoBanner() {
  return (
    <aside className="demo-banner" role="note">
      <strong>Simulated class.</strong> These 60 students are invented: a held-out simulation made
      with the same grader, not real people. Risk scores and marks are signals for a teacher to
      look closer, never a verdict. No student code is shown.{" "}
      <Link href="/">Back to the problems</Link>
    </aside>
  );
}
