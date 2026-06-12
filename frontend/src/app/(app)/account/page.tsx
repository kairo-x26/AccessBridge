import type { Metadata } from "next";

import { Account } from "./Account";

export const metadata: Metadata = { title: "Your account" };

export default function AccountPage() {
  return <Account />;
}
