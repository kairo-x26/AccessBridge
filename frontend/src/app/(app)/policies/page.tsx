import type { Metadata } from "next";

import { Policies } from "./Policies";

export const metadata: Metadata = { title: "Policies" };

export default function PoliciesPage() {
  return <Policies />;
}
