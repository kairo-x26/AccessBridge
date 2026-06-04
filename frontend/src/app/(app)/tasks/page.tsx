import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/States";

import { Tasks } from "./Tasks";

export const metadata: Metadata = { title: "Tasks" };

export default function TasksPage() {
  return (
    <Suspense fallback={<Skeleton lines={6} />}>
      <Tasks />
    </Suspense>
  );
}
