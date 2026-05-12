import { EVIDENCE_LABEL, STATUS_LABEL, label, type Status } from "@/lib/format";

import styles from "./Badge.module.css";

const TONE: Record<Status, string> = {
  imported: "neutral",
  needs_review: "neutral",
  ready: "route",
  submitted: "route",
  acknowledged: "route",
  scheduled: "route",
  completed: "verified",
  exception: "exception",
  declined: "closed",
  cancelled: "closed",
};

export function StatusBadge({ status }: { status: string }) {
  const tone = TONE[status as Status] ?? "neutral";
  return (
    <span className={`${styles.badge} ${styles[tone]}`}>
      {STATUS_LABEL[status as Status] ?? status}
    </span>
  );
}

export function Tag({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "route" | "verified" | "exception" | "closed" | "alert" | "agent";
}) {
  return <span className={`${styles.badge} ${styles[tone]}`}>{children}</span>;
}

/** Evidence attached to a change. Proposed (agent, unapproved) evidence is dashed violet. */
export function EvidenceChip({
  type,
  reference,
  proposed = false,
}: {
  type: string | null;
  reference?: string | null;
  proposed?: boolean;
}) {
  if (!type) return null;
  return (
    <span
      className={`${styles.evidence} ${proposed ? styles.proposed : styles.verifiedEvidence}`}
      title={reference ?? undefined}
    >
      {label(EVIDENCE_LABEL, type)}
    </span>
  );
}
