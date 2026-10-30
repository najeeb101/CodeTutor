"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { InstructorStudent } from "@/lib/types";

import { Bar } from "./Bar";
import { formatNumber, formatWhen } from "./format";

type SortKey = keyof Pick<
  InstructorStudent,
  | "name"
  | "problems_solved"
  | "first_try_solve_share"
  | "skill"
  | "submissions_to_review"
  | "last_active"
>;

const COLUMNS: [SortKey, string][] = [
  ["name", "Student"],
  ["problems_solved", "Solved / tried"],
  ["first_try_solve_share", "First try"],
  ["skill", "Skill"],
  ["submissions_to_review", "To look at"],
  ["last_active", "Last active"],
];

// Returns a negative number if a sorts before b, positive if after, 0 if equal.
// Values are strings (name, last_active as an ISO date), numbers, or null (nothing measured yet).
function compareValues(a: string | number | null, b: string | number | null): number {
  // TODO(najeeb): a student with no skill yet (null) must always sort LAST, whether the teacher
  // sorts up or down. Hint: this function only decides "up"; handle null first, and let the
  // caller (see `rows` below) keep nulls at the end when it flips the direction.
  if (a === null || b === null) return 0;
  if (typeof a === "string" && typeof b === "string") return a.localeCompare(b);
  return Number(a) - Number(b);
}

export function StudentTable({ students }: { students: InstructorStudent[] }) {
  // null = the order the API sent (most to look at first).
  const [sort, setSort] = useState<{ key: SortKey; down: boolean } | null>(null);

  const rows = useMemo(() => {
    if (sort === null) return students;
    const direction = sort.down ? -1 : 1;
    return [...students].sort((a, b) => direction * compareValues(a[sort.key], b[sort.key]));
  }, [students, sort]);

  function click(key: SortKey) {
    setSort((old) => (old?.key === key ? { key, down: !old.down } : { key, down: false }));
  }

  return (
    <table className="data">
      <thead>
        <tr>
          {COLUMNS.map(([key, label]) => (
            <th key={key} aria-sort={sort?.key === key ? (sort.down ? "descending" : "ascending") : "none"}>
              <button type="button" onClick={() => click(key)}>
                {label}
                {sort?.key === key ? (sort.down ? " ↓" : " ↑") : ""}
              </button>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((student) => (
          <tr key={student.id}>
            <td>
              <Link href={`/instructor/students/${student.id}`}>{student.name}</Link>
            </td>
            <td>
              {student.problems_solved} / {student.problems_tried}
            </td>
            <td>
              <Bar share={student.first_try_solve_share} />
            </td>
            <td>{formatNumber(student.skill)}</td>
            <td>{student.submissions_to_review || <span className="muted">0</span>}</td>
            <td>{formatWhen(student.last_active)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
