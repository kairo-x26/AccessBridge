import type { Metadata } from "next";

import { Approvals } from "./Approvals";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsPage() {
  return <Approvals />;
}
