"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { TEACHER_VIEW } from "@/components/instructor/DashboardView";
import { StudentDetailView } from "@/components/instructor/StudentDetailView";
import { TokenGate } from "@/components/instructor/TokenGate";

export default function StudentPage() {
  const params = useParams<{ id: string }>();
  return (
    <>
      <p>
        <Link href="/instructor">← Dashboard</Link>
      </p>
      <TokenGate>
        <StudentDetailView id={params.id} view={TEACHER_VIEW} />
      </TokenGate>
    </>
  );
}
