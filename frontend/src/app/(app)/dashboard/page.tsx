import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/States";

import { Dashboard } from "./Dashboard";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <Suspense fallback={<Skeleton lines={8} />}>
      <Dashboard />
    </Suspense>
  );
}
