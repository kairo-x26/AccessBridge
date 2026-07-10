import type { Metadata } from "next";
import { Suspense } from "react";

import { AcceptInvitation } from "./AcceptInvitation";

export const metadata: Metadata = { title: "Join your team" };

export default function Page() {
  return (
    <Suspense>
      <AcceptInvitation />
    </Suspense>
  );
}
