"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { DEMO_VIEW } from "@/components/instructor/DashboardView";
import { DemoBanner } from "@/components/instructor/DemoBanner";
import { StudentDetailView } from "@/components/instructor/StudentDetailView";

export default function DemoStudentPage() {
  const params = useParams<{ id: string }>();
  return (
    <>
      <p>
        <Link href="/demo">← Teacher view (demo)</Link>
      </p>
      <DemoBanner />
      <StudentDetailView id={params.id} view={DEMO_VIEW} />
    </>
  );
}
