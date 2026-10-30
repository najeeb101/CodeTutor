import type { InstructorProblem } from "@/lib/types";

import { Bar } from "./Bar";
import { formatNumber } from "./format";

export function ProblemTable({ problems }: { problems: InstructorProblem[] }) {
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Problem</th>
          <th>Module</th>
          <th>Declared</th>
          <th>Measured difficulty</th>
          <th>Students</th>
          <th>First try</th>
        </tr>
      </thead>
      <tbody>
        {problems.map((problem) => (
          <tr key={problem.id}>
            <td>{problem.title}</td>
            <td>{problem.module}</td>
            <td>{problem.declared_difficulty}</td>
            <td>{formatNumber(problem.estimated_difficulty)}</td>
            <td>{problem.students}</td>
            <td>
              <Bar share={problem.first_try_solve_share} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
