"use client";

import Link from "next/link";
import { useState } from "react";
import useSWRInfinite from "swr/infinite";

import { PageHeader } from "@/components/app/PageHeader";
import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import tableStyles from "@/components/ui/Table.module.css";
import { fetcher, type AuditItem } from "@/lib/api";
import { actorLabel, formatDateTime } from "@/lib/format";
import { useStaffNames } from "@/lib/hooks";

import styles from "./audit.module.css";

type AuditPage = { items: AuditItem[]; next_before: string | null };

const OPERATIONS: Record<string, string> = {
  "": "Every operation",
  "auth.": "Sign-ins",
  "referral.": "Referral changes and views",
  "document.": "Document access",
  "agent.": "Agent proposals and actions",
  "approval.": "Approval decisions",
  "message.": "Patient messages",
  "user.": "User management",
  "integration.": "Integration updates",
  "template.": "Template changes",
};

const OUTCOME_TONE: Record<string, "verified" | "alert" | "exception" | "neutral" | "agent"> = {
  success: "verified",
  denied: "alert",
  rejected: "alert",
  failed: "alert",
  locked: "alert",
  approval_required: "agent",
  duplicate: "neutral",
};

function resourceLink(ref: string | null) {
  if (!ref) return "—";
  if (ref.startsWith("ref_")) return <Link href={`/referrals/${ref}`}>{ref}</Link>;
  return ref;
}

export function AuditLog() {
  const { names } = useStaffNames();
  const [operation, setOperation] = useState("");
  const [resource, setResource] = useState("");
  const base = new URLSearchParams({ limit: "50" });
  if (operation) base.set("operation", operation);
  if (resource.trim()) base.set("resource_ref", resource.trim());

  const { data, error, size, setSize, isValidating, mutate } = useSWRInfinite<AuditPage>(
    (i, prev) => {
      if (prev && !prev.next_before) return null;
      const q = new URLSearchParams(base);
      if (i > 0 && prev?.next_before) q.set("before", prev.next_before);
      return `/audit-events?${q}`;
    },
    fetcher,
  );
  const rows = data?.flatMap((p) => p.items) ?? [];
  const more = !!data?.at(-1)?.next_before;

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who did what, when, and with what authority. Entries can't be edited or deleted."
      />
      <div className={styles.filters}>
        <label>
          <span className="visually-hidden">Operation</span>
          <select className={inputClass} value={operation} onChange={(e) => setOperation(e.target.value)}>
            {Object.entries(OPERATIONS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="visually-hidden">Resource ID</span>
          <input className={inputClass} placeholder="Filter by record ID, e.g. ref_…" value={resource} onChange={(e) => setResource(e.target.value)} />
        </label>
      </div>
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <Skeleton lines={10} />
      ) : rows.length === 0 ? (
        <EmptyState title="No matching entries" />
      ) : (
        <>
          <div className={tableStyles.wrap}>
            <table className={tableStyles.table}>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Who</th>
                  <th scope="col">Operation</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Record</th>
                  <th scope="col">Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td className={styles.nowrap}>{formatDateTime(e.timestamp)}</td>
                    <td>
                      {actorLabel(e.actor, names)}
                      <span className={tableStyles.sub}>{e.actor}</span>
                    </td>
                    <td className={styles.op}>{e.operation}</td>
                    <td>
                      <Tag tone={OUTCOME_TONE[e.outcome] ?? "neutral"}>{e.outcome.replaceAll("_", " ")}</Tag>
                    </td>
                    <td className={styles.ref}>{resourceLink(e.resource_ref)}</td>
                    <td>
                      {Object.keys(e.details).length > 0 && (
                        <details>
                          <summary className={styles.summary}>View</summary>
                          <pre className={styles.details}>{JSON.stringify(e.details, null, 2)}</pre>
                        </details>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {more && (
            <div className={styles.more}>
              <Button busy={isValidating} onClick={() => setSize(size + 1)}>
                Load older entries
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );
}
