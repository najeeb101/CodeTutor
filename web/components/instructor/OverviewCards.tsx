import type { InstructorOverview } from "@/lib/types";

import { formatWhen } from "./format";

function percent(share: number | null): string {
  return share === null ? "–" : `${Math.round(share * 100)}%`;
}

export function OverviewCards({ overview }: { overview: InstructorOverview }) {
  const cards: [string, string][] = [
    ["Students", String(overview.students)],
    ["Submissions", `${overview.submissions} (${overview.graded} graded)`],
    ["Accepted", percent(overview.accepted_share)],
    ["Solved on first try", percent(overview.first_try_solve_share)],
    ["Students to look at", String(overview.students_to_review)],
    ["Submissions to look at", String(overview.submissions_to_review)],
  ];
  return (
    <>
      <ul className="cards">
        {cards.map(([label, value]) => (
          <li key={label}>
            <span className="muted">{label}</span>
            <strong>{value}</strong>
          </li>
        ))}
      </ul>
      <p className="muted">
        {overview.flags_computed_at === null
          ? "The integrity job has never run, so no submission is marked. Run `make integrity`."
          : `Integrity flags were written ${formatWhen(overview.flags_computed_at)}.`}{" "}
        A mark is a reason to look at the work, never proof.
      </p>
    </>
  );
}
