import Link from "next/link";

import { apiFetch } from "@/lib/api";
import type { ProblemSummary } from "@/lib/types";

// Ask the API on every request (a sync can change the list), never at build time.
export const dynamic = "force-dynamic";

interface ModuleGroup {
  module: number;
  name: string;
  problems: ProblemSummary[];
}

// The API already sorts by module, then order; a Map keeps that order.
function groupByModule(problems: ProblemSummary[]): ModuleGroup[] {
  const groups = new Map<number, ModuleGroup>();
  for (const problem of problems) {
    const group = groups.get(problem.module) ?? {
      module: problem.module,
      name: problem.module_name,
      problems: [],
    };
    group.problems.push(problem);
    groups.set(problem.module, group);
  }
  return [...groups.values()];
}

export default async function ProblemListPage() {
  const problems = await apiFetch<ProblemSummary[]>("/api/problems");
  return (
    <>
      <h1>Problems</h1>
      <p className="muted">
        {problems.length} Python problems. Each answer is graded at once against visible and
        hidden tests.
      </p>
      {groupByModule(problems).map((group) => (
        <section key={group.module} className="module">
          <h2>
            {group.module}. {group.name}
          </h2>
          <ul className="problem-list">
            {group.problems.map((problem) => (
              <li key={problem.id}>
                <Link href={`/problems/${problem.id}`}>{problem.title}</Link>
                <span className={`badge ${problem.difficulty}`}>{problem.difficulty}</span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
