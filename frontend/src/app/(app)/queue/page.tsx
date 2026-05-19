import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/States";

import { Queue } from "./Queue";

export const metadata: Metadata = { title: "Referrals" };

export default function QueuePage() {
  return (
    <Suspense fallback={<Skeleton lines={6} />}>
      <Queue />
    </Suspense>
  );
}
