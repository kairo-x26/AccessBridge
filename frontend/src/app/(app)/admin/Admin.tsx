"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/app/PageHeader";
import { can, useMe } from "@/lib/hooks";

import styles from "../approvals/approvals.module.css";
import { Checklists } from "./Checklists";
import { Destinations } from "./Destinations";
import { OrganizationSettings } from "./OrganizationSettings";
import { People } from "./People";
import { Templates } from "./Templates";

const TABS = {
  people: { label: "People", perm: "user:manage" },
  organization: { label: "Organization", perm: "config:manage" },
  templates: { label: "Message templates", perm: "template:manage" },
  checklists: { label: "Checklists", perm: "config:manage" },
  destinations: { label: "Specialist offices", perm: "config:manage" },
} as const;
type Tab = keyof typeof TABS;

export function Admin() {
  const { data: me } = useMe();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const allowed = (Object.keys(TABS) as Tab[]).filter((t) => can(me, TABS[t].perm));
  const requested = params.get("tab") as Tab | null;
  const tab = requested && allowed.includes(requested) ? requested : allowed[0];

  return (
    <>
      <PageHeader title="Admin" description="People, security, messages and workflow rules for your organization." />
      <div className={styles.tabs} role="tablist" aria-label="Admin sections">
        {allowed.map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={styles.tab} onClick={() => router.replace(`${pathname}?tab=${t}`)}>
            {TABS[t].label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "people" && <People />}
        {tab === "organization" && <OrganizationSettings />}
        {tab === "templates" && <Templates />}
        {tab === "checklists" && <Checklists />}
        {tab === "destinations" && <Destinations />}
        {!tab && <p>You don&rsquo;t have access to any admin settings.</p>}
      </div>
    </>
  );
}
