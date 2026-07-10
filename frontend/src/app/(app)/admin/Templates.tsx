"use client";

import { useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Template } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import { useApi } from "@/lib/hooks";

import styles from "./admin.module.css";

const KEYS: Record<string, string> = {
  schedule_prompt: "Ask the patient to schedule",
  appointment_check: "Ask whether the visit happened",
};
const LANGS: Record<string, string> = { en: "English", es: "Spanish", vi: "Vietnamese", zh: "Chinese", ar: "Arabic", ht: "Haitian Creole" };

function Editor({ t, onSaved }: { t: Template; onSaved: () => void }) {
  const toast = useToast();
  const [body, setBody] = useState(t.body);
  const [editing, setEditing] = useState(false);
  async function save() {
    try {
      await api.put(`/templates/${t.key}/${t.language}`, { body });
      toast("Saved as a new version. Another administrator must review it before it's used.");
      setEditing(false);
      onSaved();
    } catch (err) {
      toast(err instanceof ApiError ? (err.reasons[0] ?? err.message) : "Not saved.", "error");
    }
  }
  if (!editing)
    return (
      <Button size="sm" onClick={() => setEditing(true)}>
        {t.builtin ? "Adopt and edit" : "Edit"}
      </Button>
    );
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <label>
        <span className="visually-hidden">Message text</span>
        <textarea className={inputClass} rows={5} value={body} onChange={(e) => setBody(e.target.value)} />
      </label>
      <p className={styles.muted}>
        Placeholders: {"{first_name}"}, {"{clinic_name}"}, {"{specialist_office}"}, {"{specialist_phone}"}. Keep it administrative and include
        &ldquo;Reply STOP&rdquo;.
      </p>
      <div style={{ display: "flex", gap: 8 }}>
        <Button size="sm" variant="primary" onClick={save}>
          Save for review
        </Button>
        <Button size="sm" variant="quiet" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function Templates() {
  const toast = useToast();
  const { data: me } = useMe();
  const { data, mutate } = useApi<Template[]>("/templates");
  if (!data) return <Skeleton lines={6} />;

  // Show the newest version per key+language.
  const latest = new Map<string, Template>();
  for (const t of data) {
    const k = `${t.key}:${t.language}`;
    const cur = latest.get(k);
    if (!cur || t.version > cur.version) latest.set(k, t);
  }

  async function review(t: Template) {
    try {
      await api.post(`/templates/${t.id}/review`);
      toast("Reviewed. This version is now in use.");
      mutate();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not reviewed.", "error");
    }
  }

  return (
    <div className={styles.templateGrid}>
      {[...latest.values()].map((t) => (
        <Panel
          key={`${t.key}${t.language}`}
          title={KEYS[t.key] ?? t.key}
          description={LANGS[t.language] ?? t.language}
          actions={
            t.builtin ? <Tag>Starting point</Tag> : t.active ? <Tag tone="verified">In use, v{t.version}</Tag> : <Tag tone="exception">Needs review, v{t.version}</Tag>
          }
        >
          <div style={{ display: "grid", gap: 12 }}>
            <p className={styles.templateBody}>{t.body}</p>
            {!t.builtin && !t.active && !t.reviewed_by && (
              t.author === `user:${me?.id}` ? (
                <p className={styles.muted}>Waiting for another administrator to review.</p>
              ) : (
                <Button size="sm" variant="primary" onClick={() => review(t)}>
                  Review and put in use
                </Button>
              )
            )}
            <Editor t={t} onSaved={() => mutate()} />
          </div>
        </Panel>
      ))}
    </div>
  );
}
