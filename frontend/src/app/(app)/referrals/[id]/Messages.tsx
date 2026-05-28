"use client";

import { Send, UserRoundCog } from "lucide-react";
import { useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, newIdempotencyKey, type Communication, type ReferralDetail } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";

import styles from "./referral.module.css";

const TEMPLATES = {
  schedule_prompt: "Ask the patient to schedule",
  appointment_check: "Ask whether the visit happened",
};
const CLASS_LABEL: Record<string, { text: string; tone: "verified" | "route" | "exception" | "closed" | "alert" | "neutral" }> = {
  confirmed: { text: "Says they have an appointment", tone: "verified" },
  needs_assistance: { text: "Asked for help", tone: "exception" },
  declined: { text: "May not want the referral", tone: "closed" },
  opt_out: { text: "Opted out", tone: "closed" },
  unknown: { text: "Needs reading", tone: "neutral" },
};
const STATUS_TEXT: Record<string, string> = {
  sent: "Sent",
  delivered: "Delivered",
  failed: "Not delivered",
  suppressed: "Not sent",
  queued: "Queued",
  received: "Received",
};

type Preview = { can_send: boolean; problems: string[]; body: string | null; language: string | null };

export function Messages({ referral, canSend, onChange }: { referral: ReferralDetail; canSend: boolean; onChange: () => void }) {
  const toast = useToast();
  const { data: messages, mutate } = useApi<Communication[]>(`/referrals/${referral.id}/communications`);
  const [composing, setComposing] = useState(false);
  const [editingContact, setEditingContact] = useState(false);
  const [template, setTemplate] = useState<keyof typeof TEMPLATES>("schedule_prompt");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const p = referral.patient;

  async function loadPreview(key: keyof typeof TEMPLATES) {
    setTemplate(key);
    setPreview(await api.post<Preview>(`/referrals/${referral.id}/communications/preview`, { template_key: key }));
  }

  async function send() {
    setBusy(true);
    try {
      await api.post(`/referrals/${referral.id}/communications`, { template_key: template }, { "idempotency-key": newIdempotencyKey() });
      toast("Message sent.");
      setComposing(false);
      mutate();
      onChange();
    } catch (err) {
      toast(err instanceof ApiError ? (err.reasons[0] ?? err.message) : "Not sent.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveContact(form: FormData) {
    try {
      await api.patch(`/patients/${p.id}/contact`, {
        phone: String(form.get("phone") || "") || undefined,
        preferred_language: String(form.get("preferred_language")),
        preferred_channel: String(form.get("preferred_channel")),
        consent_reference: String(form.get("consent_reference") || "") || undefined,
        contact_verified: form.get("contact_verified") === "on",
        opted_out: form.get("opted_out") === "on",
        needs_interpreter: form.get("needs_interpreter") === "on",
        transportation_need: form.get("transportation_need") === "on",
      });
      toast("Contact details saved.");
      setEditingContact(false);
      onChange();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not saved.", "error");
    }
  }

  return (
    <Panel
      title="Patient messages"
      description="Administrative text messages only. Medical questions go to clinical staff."
      actions={
        canSend && (
          <>
            <Button size="sm" icon={<UserRoundCog />} onClick={() => setEditingContact(true)}>
              Contact & consent
            </Button>
            <Button
              size="sm"
              icon={<Send />}
              onClick={() => {
                setComposing(true);
                loadPreview(template);
              }}
            >
              Send a message
            </Button>
          </>
        )
      }
    >
      <dl className={styles.contactFacts}>
        <dt>Language</dt>
        <dd>{p.preferred_language === "es" ? "Spanish" : p.preferred_language === "en" ? "English" : p.preferred_language}</dd>
        <dt>Texts</dt>
        <dd>{p.opted_out ? "Opted out" : p.contact_verified ? "Verified number" : "Number not verified"}</dd>
        {p.needs_interpreter && (
          <>
            <dt>Support</dt>
            <dd>Needs an interpreter</dd>
          </>
        )}
        {p.transportation_need && (
          <>
            <dt>Support</dt>
            <dd>Needs transportation help</dd>
          </>
        )}
      </dl>
      {!messages?.length ? (
        <p className={styles.muted}>No messages yet.</p>
      ) : (
        <ol className={styles.thread}>
          {messages.map((m) => (
            <li key={m.id} className={m.direction === "inbound" ? styles.inbound : styles.outbound}>
              <div className={styles.bubbleMeta}>
                <span>{m.direction === "inbound" ? "Patient" : m.created_by.startsWith("agent") ? "Agent (approved)" : "Clinic"}</span>
                <time>{formatDateTime(m.created_at)}</time>
              </div>
              <p className={styles.bubble}>{m.body ?? <em>Message text not available</em>}</p>
              <div className={styles.bubbleMeta}>
                {m.direction === "outbound" ? (
                  <Tag tone={m.status === "delivered" ? "verified" : m.status === "failed" || m.status === "suppressed" ? "alert" : "neutral"}>
                    {STATUS_TEXT[m.status] ?? m.status}
                  </Tag>
                ) : (
                  <>
                    {m.escalated && <Tag tone="alert">Escalated to staff</Tag>}
                    {m.classification && (
                      <Tag tone={CLASS_LABEL[m.classification]?.tone ?? "neutral"}>{CLASS_LABEL[m.classification]?.text ?? m.classification}</Tag>
                    )}
                  </>
                )}
                {m.failure_reason && <span className={styles.muted}>{m.failure_reason}</span>}
              </div>
            </li>
          ))}
        </ol>
      )}

      <Dialog
        open={composing}
        onClose={() => setComposing(false)}
        title="Send a message"
        footer={
          <>
            <Button onClick={() => setComposing(false)}>Cancel</Button>
            <Button variant="primary" busy={busy} disabled={!preview?.can_send} onClick={send}>
              Send message
            </Button>
          </>
        }
      >
        <Field label="Message">
          {(fp) => (
            <select {...fp} className={inputClass} value={template} onChange={(e) => loadPreview(e.target.value as keyof typeof TEMPLATES)}>
              {Object.entries(TEMPLATES).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          )}
        </Field>
        {preview?.body && <blockquote className={styles.previewBody}>{preview.body}</blockquote>}
        {preview && !preview.can_send && (
          <Notice tone="warning" title="This message can't be sent">
            <ul>
              {preview.problems.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </Notice>
        )}
      </Dialog>

      <Dialog open={editingContact} onClose={() => setEditingContact(false)} title="Contact & consent">
        <form
          style={{ display: "grid", gap: 14 }}
          onSubmit={(e) => {
            e.preventDefault();
            saveContact(new FormData(e.currentTarget));
          }}
        >
          <Field label="Mobile number" hint="Changing the number clears verification.">
            {(fp) => <input {...fp} name="phone" className={inputClass} defaultValue={p.phone ?? ""} />}
          </Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Language">
              {(fp) => (
                <select {...fp} name="preferred_language" className={inputClass} defaultValue={p.preferred_language}>
                  <option value="en">English</option>
                  <option value="es">Spanish</option>
                  <option value="vi">Vietnamese</option>
                  <option value="zh">Chinese</option>
                  <option value="ar">Arabic</option>
                  <option value="ht">Haitian Creole</option>
                </select>
              )}
            </Field>
            <Field label="Preferred contact">
              {(fp) => (
                <select {...fp} name="preferred_channel" className={inputClass} defaultValue={p.preferred_channel}>
                  <option value="sms">Text message</option>
                  <option value="phone">Phone call</option>
                  <option value="email">Email</option>
                </select>
              )}
            </Field>
          </div>
          <Field label="Consent reference" hint="Where the patient's consent to texts is recorded, e.g. the signed form ID.">
            {(fp) => <input {...fp} name="consent_reference" className={inputClass} />}
          </Field>
          <fieldset className={styles.checks}>
            <legend className="visually-hidden">Contact status</legend>
            <label><input type="checkbox" name="contact_verified" defaultChecked={p.contact_verified} /> Number verified with the patient</label>
            <label><input type="checkbox" name="opted_out" defaultChecked={p.opted_out} /> Patient opted out of texts</label>
            <label><input type="checkbox" name="needs_interpreter" defaultChecked={p.needs_interpreter} /> Needs an interpreter</label>
            <label><input type="checkbox" name="transportation_need" defaultChecked={p.transportation_need} /> Needs transportation help</label>
          </fieldset>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={() => setEditingContact(false)}>Cancel</Button>
            <Button type="submit" variant="primary">Save contact details</Button>
          </div>
        </form>
      </Dialog>
    </Panel>
  );
}
