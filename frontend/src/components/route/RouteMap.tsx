import type { ReactNode } from "react";

import { EvidenceChip } from "@/components/ui/Badge";
import type { StatusEvent } from "@/lib/api";
import {
  ROUTE,
  STATUS_LABEL,
  TOOL_LABEL,
  actorLabel,
  formatDateTime,
  label,
  type Status,
} from "@/lib/format";

import styles from "./RouteMap.module.css";

export type Proposal = {
  approvalId: string;
  tool: string;
  reason: string;
};

/** Which stop an approval-gated agent action would move the referral to. */
export const TOOL_TARGET: Record<string, Status> = {
  transmit_referral_package: "submitted",
  record_scheduled: "scheduled",
  propose_completion: "completed",
  flag_exception: "exception",
};

const OFF = new Set(["exception", "declined", "cancelled"]);

type Branch = { event: StatusEvent; kind: "off" | "return" };

function layout(events: StatusEvent[]) {
  const entered: Partial<Record<Status, StatusEvent>> = {};
  const branches: Partial<Record<Status, Branch[]>> = {};
  let last: Status = "imported";
  for (const e of events) {
    const to = e.new_status as Status;
    if (OFF.has(to)) {
      (branches[last] ??= []).push({ event: e, kind: "off" });
      continue;
    }
    if (e.old_status === "exception") (branches[last] ??= []).push({ event: e, kind: "return" });
    entered[to] = e;
    last = to;
  }
  return { entered, branches };
}

/**
 * The referral's journey drawn as a vertical transit map. Every stop shows the evidence that
 * moved the referral there. Agent proposals waiting for approval are drawn as dashed violet
 * stops: visible, but clearly not done.
 */
export function RouteMap({
  status,
  progress,
  events,
  proposals = [],
  names = {},
  renderProposalAction,
}: {
  status: string;
  progress: string;
  events: StatusEvent[];
  proposals?: Proposal[];
  names?: Record<string, string>;
  renderProposalAction?: (p: Proposal) => ReactNode;
}) {
  const { entered, branches } = layout(events);
  const reached = ROUTE.findIndex((r) => r.status === (OFF.has(status) ? progress : status));
  const proposalsByStop: Partial<Record<Status, Proposal[]>> = {};
  for (const p of proposals) {
    const target = TOOL_TARGET[p.tool];
    if (target && target !== "exception") (proposalsByStop[target] ??= []).push(p);
  }
  const exceptionProposals = proposals.filter((p) => TOOL_TARGET[p.tool] === "exception");

  return (
    <ol className={styles.map} aria-label="Referral route">
      {ROUTE.map((stop, i) => {
        const ev = entered[stop.status];
        const state =
          i < reached || (i === reached && status === "completed")
            ? "done"
            : i === reached
              ? OFF.has(status)
                ? "left"
                : "current"
              : "ahead";
        const proposed = state === "ahead" ? proposalsByStop[stop.status] : undefined;
        const isLast = i === ROUTE.length - 1;
        const segDone = i < reached;
        return (
          <li
            key={stop.status}
            className={`${styles.stop} ${styles[state]} ${proposed ? styles.proposed : ""}`}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className={styles.rail} aria-hidden="true">
              <span className={styles.marker} />
              {!isLast && <span className={`${styles.segment} ${segDone ? styles.segmentDone : ""}`} />}
            </span>
            <div className={styles.content}>
              <div className={styles.titleRow}>
                <span className={styles.name}>{STATUS_LABEL[stop.status]}</span>
                {state === "current" && <span className={styles.now}>Now</span>}
                {ev && state !== "ahead" && <time className={styles.time}>{formatDateTime(ev.timestamp)}</time>}
              </div>
              {ev && state !== "ahead" && (
                <div className={styles.meta}>
                  <EvidenceChip type={ev.evidence_type} reference={ev.evidence_reference} />
                  <span className={styles.actor}>{actorLabel(ev.actor, names)}</span>
                  {ev.correction && <span className={styles.actor}>Correction</span>}
                </div>
              )}
              {proposed?.map((p) => (
                <div key={p.approvalId} className={styles.proposal}>
                  <p className={styles.proposalTitle}>
                    Agent proposes: {label(TOOL_LABEL, p.tool)}
                  </p>
                  <p className={styles.proposalReason}>{p.reason}</p>
                  <p className={styles.proposalNote}>Not done yet. Waiting for staff approval.</p>
                  {renderProposalAction?.(p)}
                </div>
              ))}
              {(branches[stop.status] ?? []).map(({ event, kind }) => (
                <div
                  key={event.id}
                  className={`${styles.branch} ${kind === "return" ? styles.branchReturn : styles[`branch_${event.new_status}`] ?? ""}`}
                >
                  <p className={styles.branchTitle}>
                    {kind === "return" ? "Back in review" : STATUS_LABEL[event.new_status as Status]}
                    <time className={styles.time}>{formatDateTime(event.timestamp)}</time>
                  </p>
                  {event.reason && <p className={styles.branchReason}>{event.reason}</p>}
                  <div className={styles.meta}>
                    <EvidenceChip type={event.evidence_type} reference={event.evidence_reference} />
                    <span className={styles.actor}>{actorLabel(event.actor, names)}</span>
                  </div>
                </div>
              ))}
              {i === reached &&
                exceptionProposals.map((p) => (
                  <div key={p.approvalId} className={styles.proposal}>
                    <p className={styles.proposalTitle}>Agent proposes: {label(TOOL_LABEL, p.tool)}</p>
                    <p className={styles.proposalReason}>{p.reason}</p>
                    {renderProposalAction?.(p)}
                  </div>
                ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
