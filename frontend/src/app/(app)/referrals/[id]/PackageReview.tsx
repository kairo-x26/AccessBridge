"use client";

import { Check, CircleAlert, FileText, MinusCircle, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Field, type ReferralDetail, type Validation } from "@/lib/api";
import { FIELD_LABEL, formatDateTime, label } from "@/lib/format";
import { useApi } from "@/lib/hooks";

import { DocumentViewer } from "./DocumentViewer";
import { FieldRow } from "./FieldRow";
import styles from "./referral.module.css";

type Package = { id: string; version: number; approved_by: string; approved_at: string; note: string | null };

const DOC_TYPE: Record<string, string> = {
  referral_form: "Referral form",
  insurance_card: "Insurance card",
  clinical_note: "Visit note",
  lab_result: "Lab results",
  imaging_report: "Imaging report",
  consult_note: "Consult note",
  consent_form: "Consent form",
  other: "Other",
  unclassified: "Not read yet",
};

export function PackageReview({
  referral,
  canEdit,
  canApprove,
  onChange,
}: {
  referral: ReferralDetail;
  canEdit: boolean;
  canApprove: boolean;
  onChange: () => void;
}) {
  const toast = useToast();
  const { data: validation } = useApi<Validation>(`/referrals/${referral.id}/validation`);
  const { data: fields } = useApi<Field[]>(`/referrals/${referral.id}/fields`);
  const { data: packages } = useApi<Package[]>(`/referrals/${referral.id}/packages`);
  const [viewing, setViewing] = useState<{ docId: string; field?: Field } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const inReview = ["needs_review", "exception"].includes(referral.status);

  const openIssues = new Map((validation?.issues ?? []).filter((i) => i.status !== "resolved").map((i) => [i.item_key, i]));
  const docName = (id: string) => referral.documents.find((d) => d.id === id)?.filename ?? "document";
  const byName = new Map<string, Field[]>();
  for (const f of fields ?? []) byName.set(f.name, [...(byName.get(f.name) ?? []), f]);

  async function approve() {
    setBusy(true);
    try {
      await api.post(`/referrals/${referral.id}/package/approve`, { expected_version: referral.version });
      toast("Package approved. The agent will prepare it for sending, with your approval.");
      onChange();
      setTimeout(onChange, 1500);
    } catch (err) {
      if (err instanceof ApiError && err.reasons.length) toast(err.reasons[0], "error");
      else toast(err instanceof Error ? err.message : "Couldn't approve.", "error");
      onChange();
    } finally {
      setBusy(false);
    }
  }

  async function reopen() {
    setBusy(true);
    try {
      await api.post(`/referrals/${referral.id}/status-events`, {
        to_status: "needs_review",
        expected_version: referral.version,
      });
      toast("Back in review.");
      onChange();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Couldn't move it back.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    try {
      await api.upload(`/referrals/${referral.id}/documents`, file);
      toast(`${file.name} added. Ask the agent to read it, or it will on its next check.`);
      onChange();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Upload failed.", "error");
    }
  }

  const latest = packages?.at(-1);

  return (
    <Panel
      title="Referral package"
      description={
        inReview
          ? "Confirm what the documents say and fill what's missing. Nothing is sent until you approve."
          : latest
            ? `Version ${latest.version} approved ${formatDateTime(latest.approved_at)}.`
            : "Documents and details on file."
      }
      actions={
        canEdit && (
          <>
            <input
              ref={fileRef}
              type="file"
              hidden
              accept=".pdf,.txt,.png,.jpg,.jpeg"
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
            />
            <Button size="sm" icon={<Upload />} onClick={() => fileRef.current?.click()}>
              Add document
            </Button>
          </>
        )
      }
    >
      {!validation || !fields ? (
        <Skeleton lines={5} label="Loading package" />
      ) : (
        <div className={styles.stack}>
          {referral.status === "exception" && canEdit && (
            <Notice
              tone="warning"
              title="Fix the problem, then move the referral back to review"
              action={
                <Button busy={busy} onClick={reopen}>
                  Move back to review
                </Button>
              }
            >
              The package can be checked and approved again once the referral is back in review.
            </Notice>
          )}
          {referral.status === "needs_review" && (
            validation.ready ? (
              <Notice
                tone="success"
                title="Ready to approve"
                action={
                  canApprove && (
                    <Button variant="primary" busy={busy} onClick={approve}>
                      Approve package
                    </Button>
                  )
                }
              >
                Every required item is present and critical details are confirmed.
              </Notice>
            ) : (
              <Notice tone="warning" title="Not ready yet">
                <ul>
                  {validation.blockers.slice(0, 6).map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              </Notice>
            )
          )}

          <section aria-labelledby="checklist-h">
            <h3 id="checklist-h" className={styles.subhead}>
              Checklist <span className={styles.muted}>{validation.checklist_version === "builtin" ? "standard" : validation.checklist_version}</span>
            </h3>
            <ul className={styles.checklist}>
              {validation.checklist.map((item) => {
                const key = String(item.key);
                const issue = openIssues.get(key);
                const state = !issue ? "met" : issue.status === "waived" ? "waived" : "missing";
                return (
                  <li key={key} className={styles[`check_${state}`]}>
                    {state === "met" ? <Check aria-hidden="true" /> : state === "waived" ? <MinusCircle aria-hidden="true" /> : <CircleAlert aria-hidden="true" />}
                    <span>{String(item.label)}</span>
                    <span className={styles.checkState}>
                      {state === "met" ? "Present" : state === "waived" ? `Waived: ${issue?.resolution}` : item.blocking ? "Missing" : "Missing (optional)"}
                    </span>
                  </li>
                );
              })}
              {[...openIssues.values()]
                .filter((i) => i.status === "open" && !validation.checklist.some((c) => c.key === i.item_key))
                .map((i) => (
                  <li key={i.id} className={styles.check_missing}>
                    <CircleAlert aria-hidden="true" />
                    <span>{i.message}</span>
                    <span className={styles.checkState}>{i.severity === "blocking" ? "Blocks approval" : "Check"}</span>
                  </li>
                ))}
            </ul>
          </section>

          <section aria-labelledby="fields-h">
            <h3 id="fields-h" className={styles.subhead}>
              What the documents say
            </h3>
            {!inReview && byName.size > 0 ? (
              <details className={styles.collapsed}>
                <summary>Show {byName.size} details read from the documents</summary>
                <ul className={styles.fields}>
                  {[...byName.entries()].map(([name, list]) => (
                    <FieldRow
                      key={name}
                      label={label(FIELD_LABEL, name)}
                      fields={list}
                      docName={docName}
                      editable={false}
                      onShow={(f) => setViewing({ docId: f.document_id, field: f })}
                      onChange={onChange}
                    />
                  ))}
                </ul>
              </details>
            ) : byName.size === 0 ? (
              <p className={styles.muted}>No details read yet. Ask the agent to check, or add documents.</p>
            ) : (
              <ul className={styles.fields}>
                {[...byName.entries()].map(([name, list]) => (
                  <FieldRow
                    key={name}
                    label={label(FIELD_LABEL, name)}
                    fields={list}
                    docName={docName}
                    editable={canEdit && inReview}
                    onShow={(f) => setViewing({ docId: f.document_id, field: f })}
                    onChange={onChange}
                  />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="docs-h">
            <h3 id="docs-h" className={styles.subhead}>
              Documents
            </h3>
            <ul className={styles.docs}>
              {referral.documents.map((d) => (
                <li key={d.id}>
                  <FileText aria-hidden="true" />
                  <button type="button" className={styles.linkButton} onClick={() => setViewing({ docId: d.id })}>
                    {d.filename}
                  </button>
                  <Tag tone={d.doc_type === "unclassified" ? "neutral" : d.extraction_status === "done" ? "route" : "exception"}>
                    {DOC_TYPE[d.doc_type] ?? d.doc_type}
                  </Tag>
                  {d.extraction_status === "needs_ocr" && <span className={styles.muted}>Scanned; needs a person to read it</span>}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
      <DocumentViewer
        documentId={viewing?.docId ?? null}
        title={viewing ? docName(viewing.docId) : ""}
        highlight={viewing?.field ? [viewing.field.span_start, viewing.field.span_end] : undefined}
        onClose={() => setViewing(null)}
      />
    </Panel>
  );
}
