import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/States";

import { Admin } from "./Admin";

export const metadata: Metadata = { title: "Admin" };

export default function AdminPage() {
  return (
    <Suspense fallback={<Skeleton lines={6} />}>
      <Admin />
    </Suspense>
  );
}
