"use client";

import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/PageHeader";
import { StatusBadge, Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { api, type InboxItem } from "@/lib/api";
import { relative } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import styles from "./inbox.module.css";

const CLASS_TEXT: Record<string, string> = {
  confirmed: "Says they have an appointment",
  needs_assistance: "Asked for help",
  declined: "May not want the referral",
  opt_out: "Opted out of texts",
  unknown: "Needs reading",
};

function Reply({ m, canResolve, onDone }: { m: InboxItem; canResolve: boolean; onDone: () => void }) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  async function resolve() {
    await api.post(`/communications/${m.id}/resolve`, { note });
    toast("Marked as handled.");
    onDone();
  }
  return (
    <li className={`${styles.reply} ${m.escalated ? styles.escalated : ""}`}>
      <div className={styles.head}>
        {m.referral_id ? <Link href={`/referrals/${m.referral_id}`}>{m.patient_name}</Link> : <strong>Unknown sender</strong>}
        {m.referral_status && <StatusBadge status={m.referral_status} />}
        {m.escalated && <Tag tone="alert">Needs clinical staff</Tag>}
        {m.classification && !m.escalated && <Tag>{CLASS_TEXT[m.classification] ?? m.classification}</Tag>}
        <time className={styles.time}>{relative(m.created_at)}</time>
      </div>
      <blockquote className={styles.body}>{m.body}</blockquote>
      {m.escalated && (
        <p className={styles.note}>
          This reply may describe a medical concern. Don&rsquo;t answer by text; have clinical staff call the patient.
        </p>
      )}
      {canResolve && !m.resolved_at && (
        open ? (
          <div className={styles.resolve}>
            <label>
              <span className="visually-hidden">What did you do?</span>
              <input className={inputClass} placeholder="What did you do? e.g. Called and booked a ride" value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
            </label>
            <Button size="sm" variant="primary" disabled={note.trim().length < 2} onClick={resolve}>
              Mark handled
            </Button>
          </div>
        ) : (
          <Button size="sm" onClick={() => setOpen(true)}>
            Mark handled
          </Button>
        )
      )}
    </li>
  );
}

export function Inbox() {
  const { data: me } = useMe();
  const [all, setAll] = useState(false);
  const { data, error, mutate } = useApi<InboxItem[]>(`/communications/inbox${all ? "?include_resolved=true" : ""}`, {
    refreshInterval: 20_000,
  });
  return (
    <>
      <PageHeader
        title="Patient replies"
        description="Text replies from patients, with anything that sounds medical or urgent at the top."
        actions={
          <Button size="sm" onClick={() => setAll((a) => !a)} aria-pressed={all}>
            {all ? "Hide handled replies" : "Show handled replies"}
          </Button>
        }
      />
      {error ? (
        <ErrorState error={error} retry={() => mutate()} />
      ) : !data ? (
        <Skeleton lines={5} />
      ) : data.length === 0 ? (
        <EmptyState title="No replies waiting">Replies to reminders appear here as they arrive.</EmptyState>
      ) : (
        <ul className={styles.list}>
          {data.map((m) => (
            <Reply key={m.id} m={m} canResolve={can(me, "message:send")} onDone={() => mutate()} />
          ))}
        </ul>
      )}
    </>
  );
}
