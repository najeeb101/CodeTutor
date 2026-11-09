"use client";

import { Bar } from "@/components/instructor/Bar";
import type { View } from "@/components/instructor/DashboardView";
import { formatNumber, formatWhen } from "@/components/instructor/format";
import { useInstructorData } from "@/lib/instructorToken";
import type { InstructorStudentDetail } from "@/lib/types";

export function StudentDetailView({ id, view }: { id: string; view: View }) {
  const { data, error } = useInstructorData<InstructorStudentDetail>(
    `${view.api}/students/${encodeURIComponent(id)}`,
    view.needsToken,
  );
  if (error) {
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  }
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1>{data.name}</h1>
      <ul className="cards">
        <li>
          <span className="muted">Solved / tried</span>
          <strong>
            {data.problems_solved} / {data.problems_tried}
          </strong>
        </li>
        <li>
          <span className="muted">First try</span>
          <Bar share={data.first_try_solve_share} />
        </li>
        <li>
          <span className="muted">Skill</span>
          <strong>{formatNumber(data.skill)}</strong>
        </li>
        <li>
          <span className="muted">Risk</span>
          <Bar share={data.risk} />
        </li>
        <li>
          <span className="muted">Last active</span>
          <strong>{formatWhen(data.last_active)}</strong>
        </li>
      </ul>

      <h2>Marked submissions</h2>
      <p className="muted">
        A mark is a reason to look at the work, never proof. Honest students trigger them too (for
        example by pasting from their own editor).
      </p>
      {data.flags.length === 0 ? (
        <p>No marks.</p>
      ) : (
        <ul className="flags">
          {data.flags.map((flag) => (
            <li key={`${flag.submission_id}-${flag.kind}`}>
              <strong>{flag.problem_id}</strong> (submission {flag.submission_id}
              {flag.needs_review ? ", needs a look" : ""}): {flag.reason}
            </li>
          ))}
        </ul>
      )}

      <h2>Problems</h2>
      <table className="data">
        <thead>
          <tr>
            <th>Problem</th>
            <th>Tries</th>
            <th>Solved</th>
            <th>On first try</th>
          </tr>
        </thead>
        <tbody>
          {data.problems.map((problem) => (
            <tr key={problem.problem_id}>
              <td>{problem.title}</td>
              <td>{problem.tries}</td>
              <td>{problem.solved ? "yes" : "no"}</td>
              <td>
                {problem.solved_on_first_try === null
                  ? "not graded yet"
                  : problem.solved_on_first_try
                    ? "yes"
                    : "no"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
