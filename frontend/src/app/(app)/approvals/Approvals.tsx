"use client";

import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/PageHeader";
import { StatusBadge, Tag } from "@/components/ui/Badge";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import type { PendingApproval, Provider } from "@/lib/api";
import { SPECIALTY_LABEL, TOOL_LABEL, label, relative } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import { ApprovalActions } from "../referrals/[id]/ApprovalActions";
import styles from "./approvals.module.css";

const WHAT_HAPPENS: Record<string, string> = {
  transmit_referral_package: "Sends the approved package to the specialist office and records the receipt.",
  send_patient_message: "Texts the patient the reviewed message in their language.",
  record_scheduled: "Marks the appointment as scheduled, citing the patient's reply as evidence.",
  propose_completion: "Marks care completed, citing the specialist's consult note, and notifies clinicians.",
  flag_exception: "Moves the referral to an exception so a person takes over.",
};

function Detail({ a, providers }: { a: PendingApproval; providers: Provider[] }) {
  const args = a.action.arguments as Record<string, string>;
  if (a.action.tool === "transmit_referral_package") {
    const p = providers.find((x) => x.id === args.provider_id);
    return <p>Destination: {p ? `${p.name}${p.phone ? `, ${p.phone}` : ""}` : "unknown destination"}</p>;
  }
  if (a.action.tool === "send_patient_message") {
    return <p>Message: {args.template_key === "schedule_prompt" ? "how to schedule" : "did the visit happen"}</p>;
  }
  return null;
}

export function Approvals() {
  const { data: me } = useMe();
  const [status, setStatus] = useState<"pending" | "approved" | "rejected">("pending");
  const { data, error, mutate } = useApi<PendingApproval[]>(`/approvals?status=${status}`);
  const { data: providers } = useApi<Provider[]>("/providers");
  const canApprove = can(me, "action:approve");

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Actions the agent wants to take that need a person's go-ahead. Nothing here has happened yet."
      />
      <div className={styles.tabs} role="tablist" aria-label="Approval status">
        {(["pending", "approved", "rejected"] as const).map((s) => (
          <button key={s} type="button" role="tab" aria-selected={status === s} className={styles.tab} onClick={() => setStatus(s)}>
            {s === "pending" ? "Waiting" : s === "approved" ? "Approved" : "Rejected"}
          </button>
        ))}
      </div>
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <Skeleton lines={6} />
      ) : data.length === 0 ? (
        <EmptyState title={status === "pending" ? "Nothing waiting for approval" : "None yet"}>
          {status === "pending" ? "When the agent proposes an external action or a status change, it appears here." : null}
        </EmptyState>
      ) : (
        <ul className={styles.list}>
          {data.map((a) => (
            <li key={a.id} className={`${styles.card} ${status === "pending" ? styles.pending : ""}`}>
              <div className={styles.head}>
                <h2 className={styles.title}>{label(TOOL_LABEL, a.action.tool)}</h2>
                {a.action.external && <Tag tone="agent">Leaves AccessBridge</Tag>}
                <span className={styles.time}>Proposed {relative(a.created_at)}</span>
              </div>
              <p className={styles.who}>
                <Link href={`/referrals/${a.referral_id}`}>{a.patient_name}</Link>
                <span>{label(SPECIALTY_LABEL, a.specialty)}</span>
                <StatusBadge status={a.referral_status} />
              </p>
              <p className={styles.reason}>Why: {a.action.reason}</p>
              <Detail a={a} providers={providers ?? []} />
              <p className={styles.effect}>If approved: {WHAT_HAPPENS[a.action.tool] ?? "The agent carries out the action."}</p>
              {a.reason && <p className={styles.effect}>Note: {a.reason}</p>}
              {status === "pending" && canApprove && <ApprovalActions approvalId={a.id} onDone={() => mutate()} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
