"use client";

import { OverviewCards } from "@/components/instructor/OverviewCards";
import { ProblemTable } from "@/components/instructor/ProblemTable";
import { StudentTable } from "@/components/instructor/StudentTable";
import { TokenGate } from "@/components/instructor/TokenGate";
import { useInstructorData } from "@/lib/instructorToken";
import type { InstructorOverview, InstructorProblem, InstructorStudent } from "@/lib/types";

// Client component: the teacher token lives in the browser (sessionStorage), so the server
// render cannot ask the API for this page.
function Dashboard() {
  const overview = useInstructorData<InstructorOverview>("/api/instructor/overview");
  const students = useInstructorData<InstructorStudent[]>("/api/instructor/students");
  const problems = useInstructorData<InstructorProblem[]>("/api/instructor/problems");
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
      <StudentTable students={students.data} />
      <h2>Problems</h2>
      <p className="muted">
        Measured difficulty is also a Rasch estimate (higher = harder). It can disagree with the
        declared level, and that is worth a look.
      </p>
      <ProblemTable problems={problems.data} />
    </>
  );
}

export default function InstructorPage() {
  return (
    <>
      <h1>Instructor dashboard</h1>
      <p className="muted">
        The numbers come from whatever database the API is using. Nothing here shows student code.
      </p>
      <TokenGate>
        <Dashboard />
      </TokenGate>
    </>
  );
}
