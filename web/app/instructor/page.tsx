"use client";

import { DashboardView, TEACHER_VIEW } from "@/components/instructor/DashboardView";
import { TokenGate } from "@/components/instructor/TokenGate";

// Client component: the teacher token lives in the browser (sessionStorage), so the server
// render cannot ask the API for this page.
export default function InstructorPage() {
  return (
    <>
      <h1>Instructor dashboard</h1>
      <p className="muted">
        The numbers come from whatever database the API is using. Nothing here shows student code.
      </p>
      <TokenGate>
        <DashboardView view={TEACHER_VIEW} />
      </TokenGate>
    </>
  );
}
