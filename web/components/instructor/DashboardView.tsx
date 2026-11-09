"use client";

import { OverviewCards } from "@/components/instructor/OverviewCards";
import { ProblemTable } from "@/components/instructor/ProblemTable";
import { StudentTable } from "@/components/instructor/StudentTable";
import { useInstructorData } from "@/lib/instructorToken";
import type { InstructorOverview, InstructorProblem, InstructorStudent } from "@/lib/types";

// Where a dashboard gets its numbers and where its student pages live: the real dashboard
// (token, /api/instructor, /instructor) or the public demo (no token, /demo-api, /demo).
export interface View {
  api: string;
  pages: string;
  needsToken: boolean;
}
export const TEACHER_VIEW: View = { api: "/api/instructor", pages: "/instructor", needsToken: true };
export const DEMO_VIEW: View = { api: "/demo-api", pages: "/demo", needsToken: false };

export function DashboardView({ view }: { view: View }) {
  const overview = useInstructorData<InstructorOverview>(`${view.api}/overview`, view.needsToken);
  const students = useInstructorData<InstructorStudent[]>(`${view.api}/students`, view.needsToken);
  const problems = useInstructorData<InstructorProblem[]>(`${view.api}/problems`, view.needsToken);
  const error = overview.error ?? students.error ?? problems.error;

  if (error) {
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  }
  if (!overview.data || !students.data || !problems.data) return <p className="muted">Loading…</p>;

  return (
    <>
      <OverviewCards overview={overview.data} />
      <h2>Students</h2>
      <p className="muted">
        Skill is a Rasch estimate from first tries only (higher = more skilled). Click a column
        to sort; the default order puts the most submissions to look at first.
      </p>
      <p className="muted">
        {overview.data.risk_available
          ? "Risk is an early-warning score from weeks 1-3 (higher = may struggle later). It comes from a model fitted on a simulated class and is not shown to beat simply looking at first-try share. A reason to check in, never a verdict."
          : "Risk appears once the class has reached week 3."}
      </p>
      <StudentTable students={students.data} linkBase={view.pages} />
      <h2>Problems</h2>
      <p className="muted">
        Measured difficulty is also a Rasch estimate (higher = harder). It can disagree with the
        declared level, and that is worth a look.
      </p>
      <ProblemTable problems={problems.data} />
    </>
  );
}
