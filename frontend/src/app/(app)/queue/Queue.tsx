"use client";

import { Search, Upload } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PageHeader } from "@/components/app/PageHeader";
import { RouteLine } from "@/components/route/RouteLine";
import { StatusBadge, Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import tableStyles from "@/components/ui/Table.module.css";
import type { Page, ReferralSummary } from "@/lib/api";
import { SPECIALTY_LABEL, label } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import { ImportDialog } from "./ImportDialog";
import styles from "./queue.module.css";

const VIEWS = {
  action: { label: "Needs action", statuses: ["needs_review", "exception", "ready"] },
  moving: { label: "With specialist", statuses: ["submitted", "acknowledged", "scheduled"] },
  closed: { label: "Closed", statuses: ["completed", "declined", "cancelled"] },
  all: { label: "All", statuses: [] as string[] },
} as const;
type View = keyof typeof VIEWS;

export function Queue() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { data: me } = useMe();
  const view = (params.get("view") as View) in VIEWS ? (params.get("view") as View) : "action";
  const specialty = params.get("specialty") ?? "";
  const owner = params.get("owner") ?? "";
  const sort = params.get("sort") ?? "oldest";
  const page = Number(params.get("page") ?? "1");
  const [q, setQ] = useState(params.get("q") ?? "");
  const [importing, setImporting] = useState(false);

  function setParam(updates: Record<string, string | null>) {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(updates)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    if (!("page" in updates)) next.delete("page");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  useEffect(() => {
    const t = setTimeout(() => {
      if ((params.get("q") ?? "") !== q) setParam({ q: q || null });
    }, 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const query = new URLSearchParams({ sort, page: String(page), page_size: "25" });
  for (const s of VIEWS[view].statuses) query.append("status", s);
  if (specialty) query.set("specialty", specialty);
  if (owner === "me") query.set("owner_id", "me");
  if (owner === "unassigned") query.set("unassigned", "true");
  if (q) query.set("q", q);
  const { data, error, isLoading, mutate } = useApi<Page<ReferralSummary>>(`/referrals?${query}`, {
    keepPreviousData: true,
  });
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <PageHeader
        title="Referrals"
        description="Every referral, where it is on its route, and who owns the next step."
        actions={
          can(me, "referral:import") && (
            <Button variant="primary" icon={<Upload />} onClick={() => setImporting(true)}>
              Add referrals
            </Button>
          )
        }
      />

      <div className={styles.toolbar}>
        <div className={styles.views} role="tablist" aria-label="Referral views">
          {(Object.keys(VIEWS) as View[]).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              className={styles.view}
              onClick={() => setParam({ view: v === "action" ? null : v })}
            >
              {VIEWS[v].label}
            </button>
          ))}
        </div>
        <div className={styles.filters}>
          <label className={styles.search}>
            <Search aria-hidden="true" size={16} />
            <span className="visually-hidden">Search referrals</span>
            <input
              type="search"
              className={inputClass}
              placeholder="Name, MRN or referral ID"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </label>
          <label>
            <span className="visually-hidden">Specialty</span>
            <select className={inputClass} value={specialty} onChange={(e) => setParam({ specialty: e.target.value || null })}>
              <option value="">All specialties</option>
              {Object.entries(SPECIALTY_LABEL)
                .filter(([k]) => !["unsupported", "unspecified"].includes(k))
                .map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <span className="visually-hidden">Owner</span>
            <select className={inputClass} value={owner} onChange={(e) => setParam({ owner: e.target.value || null })}>
              <option value="">Anyone</option>
              <option value="me">Mine</option>
              <option value="unassigned">Unassigned</option>
            </select>
          </label>
          <label>
            <span className="visually-hidden">Sort</span>
            <select className={inputClass} value={sort} onChange={(e) => setParam({ sort: e.target.value === "oldest" ? null : e.target.value })}>
              <option value="oldest">Oldest first</option>
              <option value="newest">Newest first</option>
              <option value="status_changed">Longest in current step</option>
            </select>
          </label>
        </div>
      </div>

      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : isLoading && !data ? (
        <Skeleton lines={8} label="Loading referrals" />
      ) : data && data.items.length === 0 ? (
        <EmptyState title="No referrals match">
          {q || specialty || owner ? "Clear a filter or search for something else." : "New referrals appear here as soon as they're imported."}
        </EmptyState>
      ) : (
        data && (
          <>
            <div className={tableStyles.wrap}>
              <table className={tableStyles.table}>
                <caption className="visually-hidden">
                  {VIEWS[view].label} referrals, page {page} of {pages}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Patient</th>
                    <th scope="col">Route</th>
                    <th scope="col">Specialty</th>
                    <th scope="col">Owner</th>
                    <th scope="col" className={tableStyles.num}>
                      Age
                    </th>
                    <th scope="col" className={tableStyles.num}>
                      Open tasks
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.id}>
                      <td className={tableStyles.primaryCell}>
                        <Link href={`/referrals/${r.id}`}>{r.patient_name}</Link>
                        <span className={tableStyles.sub}>MRN {r.patient_ehr_id}</span>
                      </td>
                      <td>
                        <div className={styles.routeCell}>
                          <RouteLine status={r.status} progress={r.progress_status} />
                          <StatusBadge status={r.status} />
                        </div>
                      </td>
                      <td>
                        {label(SPECIALTY_LABEL, r.specialty)}
                        {r.priority_from_source !== "routine" && (
                          <span className={tableStyles.sub}>
                            <Tag tone="alert">{r.priority_from_source.replace(/^\w/, (c) => c.toUpperCase())}, per referring clinician</Tag>
                          </span>
                        )}
                      </td>
                      <td>{r.owner_name ?? <span className={styles.unassigned}>Unassigned</span>}</td>
                      <td className={tableStyles.num}>{r.age_days} d</td>
                      <td className={tableStyles.num}>{r.open_tasks || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <nav className={styles.pager} aria-label="Pages">
              <span>
                {data.total} referral{data.total === 1 ? "" : "s"}
              </span>
              <div>
                <Button size="sm" disabled={page <= 1} onClick={() => setParam({ page: String(page - 1) })}>
                  Previous
                </Button>
                <span className={styles.pageNo}>
                  Page {page} of {pages}
                </span>
                <Button size="sm" disabled={page >= pages} onClick={() => setParam({ page: String(page + 1) })}>
                  Next
                </Button>
              </div>
            </nav>
          </>
        )
      )}
      <ImportDialog open={importing} onClose={() => setImporting(false)} onDone={() => mutate()} />
    </>
  );
}
