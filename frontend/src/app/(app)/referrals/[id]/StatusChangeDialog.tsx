"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, newIdempotencyKey, type ReferralDetail } from "@/lib/api";
import { EVIDENCE_LABEL, STATUS_LABEL, label, type Status } from "@/lib/format";

const CLOSED = ["completed", "declined", "cancelled"];

/** Record an evidence-backed status change. The form only offers what the rules allow. */
export function StatusChangeDialog({
  open,
  onClose,
  referral,
  isAdmin,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  referral: ReferralDetail;
  isAdmin: boolean;
  onDone: () => void;
}) {
  const toast = useToast();
  const options = referral.next_statuses.filter((o) => o.status !== "ready");
  const correction = CLOSED.includes(referral.status) && isAdmin;
  const [target, setTarget] = useState<string>("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const chosen = options.find((o) => o.status === target);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await api.post(
        `/referrals/${referral.id}/status-events`,
        {
          to_status: correction ? "exception" : target,
          evidence_type: f.get("evidence_type") || undefined,
          evidence_reference: String(f.get("evidence_reference") ?? "").trim() || undefined,
          reason: String(f.get("reason") ?? "").trim() || undefined,
          correction,
          expected_version: referral.version,
        },
        { "idempotency-key": newIdempotencyKey() },
      );
      toast(correction ? "Referral reopened as an exception." : `Recorded: ${STATUS_LABEL[target as Status]}.`);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That change wasn't recorded.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={onClose} title={correction ? "Correct a closed referral" : "Record a change"}>
      <form onSubmit={submit} style={{ display: "grid", gap: 16 }}>
        {error && <Notice tone="error">{error}</Notice>}
        {correction ? (
          <Notice tone="warning">
            Corrections reopen the referral as an exception. The original outcome stays in the history.
          </Notice>
        ) : (
          <Field label="What happened?" hint="Only changes the referral rules allow from here are listed.">
            {(p) => (
              <select {...p} className={inputClass} value={target} onChange={(e) => setTarget(e.target.value)} required>
                <option value="" disabled>
                  Choose
                </option>
                {options.map((o) => (
                  <option key={o.status} value={o.status}>
                    {STATUS_LABEL[o.status as Status]}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        {chosen?.accepted_evidence && (
          <>
            <Field label="Evidence" hint="What proves this? Completion needs the specialist's note or confirmation.">
              {(p) => (
                <select {...p} name="evidence_type" className={inputClass} required defaultValue="">
                  <option value="" disabled>
                    Choose evidence
                  </option>
                  {chosen.accepted_evidence!.map((ev) => (
                    <option key={ev} value={ev}>
                      {label(EVIDENCE_LABEL, ev)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Field label="Evidence reference" hint="Document ID, call note, confirmation number or similar.">
              {(p) => <input {...p} name="evidence_reference" className={inputClass} required maxLength={300} />}
            </Field>
          </>
        )}
        {(correction || chosen?.reason_required) && (
          <Field label="Reason">
            {(p) => <textarea {...p} name="reason" className={inputClass} required maxLength={500} />}
          </Field>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!correction && !target}>
            {correction ? "Reopen referral" : "Record change"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
