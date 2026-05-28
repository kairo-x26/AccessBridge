"use client";

import { useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import type { Action, RunDetail, RunOut } from "@/lib/api";
import { TOOL_LABEL, label, relative } from "@/lib/format";
import { useApi } from "@/lib/hooks";

import { ApprovalActions } from "./ApprovalActions";
import styles from "./referral.module.css";

const WORKFLOW: Record<string, string> = {
  intake: "Intake check",
  follow_up: "Follow-up check",
  completion: "Completion check",
};

function outcome(a: Action): { text: string; tone: "verified" | "agent" | "alert" | "closed" | "neutral" } {
  if (a.status === "pending_approval") return { text: "Waiting for approval", tone: "agent" };
  if (a.decision === "denied") return { text: "Blocked by policy", tone: "closed" };
  if (a.status === "succeeded") return { text: a.decision === "auto" ? "Done automatically" : "Done after approval", tone: "verified" };
  if (a.status === "rejected") return { text: "Rejected by staff", tone: "closed" };
  if (a.status === "failed") return { text: "Failed", tone: "alert" };
  if (a.status === "skipped") return { text: "No longer needed", tone: "closed" };
  return { text: "In progress", tone: "neutral" };
}

function RunItem({ run, canApprove, onChange }: { run: RunOut; canApprove: boolean; onChange: () => void }) {
  const { data } = useApi<RunDetail>(`/agent-runs/${run.id}`);
  const [details, setDetails] = useState(false);
  const approvalFor = new Map((data?.approvals ?? []).map((a) => [a.action_id, a]));
  return (
    <li className={styles.run}>
      <div className={styles.runHead}>
        <span className={styles.runTitle}>{WORKFLOW[run.workflow] ?? run.workflow}</span>
        <time className={styles.muted}>{relative(run.created_at)}</time>
      </div>
      {!data ? (
        <Skeleton lines={2} />
      ) : data.actions.length === 0 ? (
        <p className={styles.muted}>Nothing to do.</p>
      ) : (
        <ul className={styles.actions}>
          {data.actions.map((a) => {
            const o = outcome(a);
            const approval = approvalFor.get(a.id);
            return (
              <li key={a.id} className={a.status === "pending_approval" ? styles.actionPending : styles.action}>
                <div className={styles.actionHead}>
                  <span className={styles.actionTool}>{label(TOOL_LABEL, a.tool)}</span>
                  <Tag tone={o.tone}>{o.text}</Tag>
                </div>
                <p className={styles.actionReason}>{a.reason}</p>
                {a.decision === "denied" && a.decision_reason && <p className={styles.muted}>Policy: {a.decision_reason}</p>}
                {a.error && <p className={styles.muted}>{a.error}</p>}
                {a.status === "pending_approval" && approval && canApprove && (
                  <ApprovalActions approvalId={approval.id} onDone={onChange} compact />
                )}
                {details && (
                  <pre className={styles.json}>
                    {JSON.stringify(
                      {
                        tool: a.tool,
                        arguments: a.arguments,
                        proposed_by: a.proposed_by,
                        confidence: a.confidence,
                        decision: a.decision,
                        authorized_by: a.authorized_by,
                        result: a.result,
                      },
                      null,
                      2,
                    )}
                  </pre>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {data && data.actions.length > 0 && (
        <button type="button" className={styles.linkButton} onClick={() => setDetails((d) => !d)} aria-expanded={details}>
          {details ? "Hide technical details" : "Show technical details"}
        </button>
      )}
      <p className={styles.runModel}>{run.model_version === "rules-v1" ? "Rules only" : `Model: ${run.model_version}`}</p>
    </li>
  );
}

/** Everything the agent proposed for this referral and what happened to each proposal. */
export function AgentActivity({ referralId, canApprove, onChange }: { referralId: string; canApprove: boolean; onChange: () => void }) {
  const { data: runs } = useApi<RunOut[]>(`/referrals/${referralId}/agent-runs`, { refreshInterval: 10_000 });
  return (
    <Panel
      tone="agent"
      title="Agent activity"
      description="The agent proposes; policy and staff decide. External actions always wait for approval."
    >
      {!runs ? (
        <Skeleton lines={4} />
      ) : runs.length === 0 ? (
        <p className={styles.muted}>The agent hasn&rsquo;t looked at this referral yet.</p>
      ) : (
        <ol className={styles.runs}>
          {runs.slice(0, 6).map((r) => (
            <RunItem key={r.id} run={r} canApprove={canApprove} onChange={onChange} />
          ))}
        </ol>
      )}
    </Panel>
  );
}
