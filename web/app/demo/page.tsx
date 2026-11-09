"use client";

import { DashboardView, DEMO_VIEW } from "@/components/instructor/DashboardView";
import { DemoBanner } from "@/components/instructor/DemoBanner";

// The teacher view of a simulated class, open to everyone (Deploy Step 2c). It asks the
// read-only demo API (/demo-api), never the real one.
export default function DemoPage() {
  return (
    <>
      <h1>Teacher view (demo)</h1>
      <DemoBanner />
      <DashboardView view={DEMO_VIEW} />
    </>
  );
}
