"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/app/PageHeader";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import type { Page, Task } from "@/lib/api";
import { can, useApi, useMe, useStaffNames } from "@/lib/hooks";

import styles from "../approvals/approvals.module.css";
import { TaskItem } from "../referrals/[id]/ReferralTasks";
import local from "./tasks.module.css";

const VIEWS = {
  mine: { label: "Mine", query: "owner=me" },
  unassigned: { label: "Unassigned", query: "owner=unassigned" },
  overdue: { label: "Overdue", query: "overdue=true" },
  all: { label: "All open", query: "" },
  closed: { label: "Finished", query: "status=closed" },
} as const;
type View = keyof typeof VIEWS;

const KINDS: Record<string, string> = {
  "": "Any kind",
  missing_info: "Missing information",
  exception: "Exceptions",
  follow_up: "Follow-ups",
  patient_assistance: "Patient help",
  reconciliation: "Specialist system updates",
  approval: "Approvals",
  review_package: "Package reviews",
};

export function Tasks() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me } = useMe();
  const { names } = useStaffNames();
  const view = ((params.get("view") as View) in VIEWS ? params.get("view") : "mine") as View;
  const kind = params.get("kind") ?? "";
  const q = [VIEWS[view].query, kind && `kind=${kind}`, "page_size=100"].filter(Boolean).join("&");
  const { data, error, mutate } = useApi<Page<Task>>(`/tasks?${q}`);

  function set(key: string, value: string | null) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  return (
    <>
      <PageHeader title="Tasks" description="Work that needs a person, most urgent first." />
      <div className={local.bar}>
        <div className={styles.tabs} role="tablist" aria-label="Task views">
          {(Object.keys(VIEWS) as View[]).map((v) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={styles.tab} onClick={() => set("view", v === "mine" ? null : v)}>
              {VIEWS[v].label}
            </button>
          ))}
        </div>
        <label>
          <span className="visually-hidden">Kind of task</span>
          <select className={local.select} value={kind} onChange={(e) => set("kind", e.target.value || null)}>
            {Object.entries(KINDS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <Skeleton lines={6} />
      ) : data.items.length === 0 ? (
        <EmptyState title={view === "mine" ? "You're all caught up" : "No tasks here"}>
          {view === "mine" ? "Check unassigned tasks, or take one from the referral queue." : null}
        </EmptyState>
      ) : (
        <ul className={local.list}>
          {data.items.map((t) => (
            <li key={t.id} className={local.row}>
              {t.referral_id && (
                <Link href={`/referrals/${t.referral_id}`} className={local.ref}>
                  Open referral
                </Link>
              )}
              <ul className={local.inner}>
                <TaskItem task={t} canManage={can(me, "task:manage") && view !== "closed"} names={names} onChange={() => mutate()} />
              </ul>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
