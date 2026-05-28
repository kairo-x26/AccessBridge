"use client";

import { Bot, Flag } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { PageHeader } from "@/components/app/PageHeader";
import { RouteMap } from "@/components/route/RouteMap";
import { StatusBadge, Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api";
import { SPECIALTY_LABEL, label } from "@/lib/format";
import { can, useMe, useStaffNames } from "@/lib/hooks";

import { AgentActivity } from "./AgentActivity";
import { ApprovalActions } from "./ApprovalActions";
import { Messages } from "./Messages";
import { OwnerPicker } from "./OwnerPicker";
import { PackageReview } from "./PackageReview";
import styles from "./referral.module.css";
import { ReferralTasks } from "./ReferralTasks";
import { StatusChangeDialog } from "./StatusChangeDialog";
import { useReferral } from "./useReferral";

const WORKFLOW_FOR: Record<string, "intake" | "follow_up" | "completion"> = {
  imported: "intake",
  needs_review: "intake",
  exception: "intake",
  ready: "intake",
  submitted: "follow_up",
  acknowledged: "follow_up",
  scheduled: "completion",
};

export function ReferralView({ id }: { id: string }) {
  const { data: r, error, mutate, pending, refresh } = useReferral(id);
  const { data: me } = useMe();
  const { names } = useStaffNames();
  const toast = useToast();
  const [changing, setChanging] = useState(false);
  const [asking, setAsking] = useState(false);

  if (error) return <ErrorState error={error} retry={() => mutate()} />;
  if (!r) return <Skeleton lines={10} label="Loading referral" />;

  const workflow = WORKFLOW_FOR[r.status];

  async function askAgent() {
    if (!workflow) return;
    setAsking(true);
    try {
      await api.post(`/referrals/${id}/analyze`, { workflow });
      toast("The agent is checking this referral. Proposals appear on the right.", "info");
      setTimeout(refresh, 1500);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't start the agent.", "error");
    } finally {
      setAsking(false);
    }
  }

  const proposals = pending.map((a) => ({ approvalId: a.id, tool: a.action.tool, reason: a.action.reason }));

  return (
    <>
      <p className={styles.back}>
        <Link href="/queue">Back to referrals</Link>
      </p>
      <PageHeader
        eyebrow={
          <>
            <span>MRN {r.patient_ehr_id}</span>
            <span>{label(SPECIALTY_LABEL, r.specialty)}</span>
            <span>
              From {r.source_system === "fhir" ? "EHR order" : r.source_system === "csv" ? "CSV import" : "manual entry"}{" "}
              {r.source_id}
            </span>
            {r.priority_from_source !== "routine" && (
              <Tag tone="alert">Marked {r.priority_from_source} by the referring clinician</Tag>
            )}
          </>
        }
        title={r.patient_name}
        description={
          <span className={styles.headline}>
            <StatusBadge status={r.status} />
            <span>
              {r.age_days} days since import, referred by {r.referring_clinician ?? "an unrecorded clinician"}
            </span>
          </span>
        }
        actions={
          <>
            {can(me, "agent:run") && workflow && (
              <Button icon={<Bot />} onClick={askAgent} busy={asking}>
                Ask the agent to check
              </Button>
            )}
            {(r.next_statuses.length > 0 ||
              (me?.role === "admin" && ["completed", "declined", "cancelled"].includes(r.status))) && (
              <Button variant="primary" icon={<Flag />} onClick={() => setChanging(true)}>
                Record a change
              </Button>
            )}
          </>
        }
      />

      {r.status === "exception" && r.exception_reason && (
        <div className={styles.banner}>
          <Notice tone="warning" title="This referral needs a person">
            {r.exception_reason}
          </Notice>
        </div>
      )}

      <div className={styles.grid}>
        <div className={styles.left}>
          <Panel title="Route" description="Each stop shows the evidence that moved the referral there.">
            <RouteMap
              status={r.status}
              progress={r.progress_status}
              events={r.events}
              proposals={proposals}
              names={names}
              renderProposalAction={
                can(me, "action:approve")
                  ? (p) => <ApprovalActions approvalId={p.approvalId} onDone={refresh} compact />
                  : undefined
              }
            />
          </Panel>
          <Panel title="Ownership">
            <OwnerPicker referral={r} canEdit={can(me, "referral:edit")} onChange={refresh} />
            {r.provider ? (
              <dl className={styles.facts}>
                <dt>Destination</dt>
                <dd>{r.provider.name}</dd>
                <dt>Office phone</dt>
                <dd>{r.provider.phone ?? "Not on file"}</dd>
                {r.appointment_at && (
                  <>
                    <dt>Appointment</dt>
                    <dd>{new Date(r.appointment_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</dd>
                  </>
                )}
              </dl>
            ) : (
              <p className={styles.muted}>No destination specialist yet.</p>
            )}
          </Panel>
        </div>

        <div className={styles.center}>
          <PackageReview referral={r} canEdit={can(me, "referral:edit")} canApprove={can(me, "package:approve")} onChange={refresh} />
          {can(me, "message:read") && <Messages referral={r} canSend={can(me, "message:send")} onChange={refresh} />}
          {can(me, "task:read") && <ReferralTasks referral={r} canManage={can(me, "task:manage")} names={names} onChange={refresh} />}
        </div>

        <aside className={styles.right} aria-label="Agent activity">
          <AgentActivity referralId={r.id} canApprove={can(me, "action:approve")} onChange={refresh} />
        </aside>
      </div>

      <StatusChangeDialog
        open={changing}
        onClose={() => setChanging(false)}
        referral={r}
        isAdmin={me?.role === "admin"}
        onDone={() => {
          setChanging(false);
          refresh();
        }}
      />
    </>
  );
}
