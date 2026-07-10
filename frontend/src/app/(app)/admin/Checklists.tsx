"use client";

import { useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Schemas } from "@/lib/api";
import { FIELD_LABEL, SPECIALTY_LABEL, label } from "@/lib/format";
import { useApi } from "@/lib/hooks";

import styles from "./admin.module.css";

type Checklist = Schemas["ChecklistOut"];
type Item = { label: string; kind: "field" | "document" | "provider"; target: string; blocking: boolean };

const DOCS: Record<string, string> = {
  referral_form: "Referral form",
  insurance_card: "Insurance card",
  clinical_note: "Visit note",
  lab_result: "Lab results",
  imaging_report: "Imaging report",
  consult_note: "Consult note",
  consent_form: "Consent form",
};

function EditChecklist({ c, onDone }: { c: Checklist; onDone: () => void }) {
  const toast = useToast();
  const [items, setItems] = useState<Item[]>(c.items.map((i) => ({ label: String(i.label), kind: i.kind as Item["kind"], target: String(i.target), blocking: Boolean(i.blocking) })));
  const set = (i: number, patch: Partial<Item>) => setItems((list) => list.map((it, j) => (j === i ? { ...it, ...patch } : it)));

  async function save() {
    try {
      await api.put(`/checklists/${c.specialty}`, { items });
      toast("Checklist saved. New referrals are checked against it.");
      onDone();
    } catch (err) {
      toast(err instanceof ApiError ? (err.reasons[0] ?? err.message) : "Not saved.", "error");
    }
  }

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <ul className={styles.itemList}>
        {items.map((it, i) => (
          <li key={i} className={styles.item}>
            <label>
              <span className="visually-hidden">Label</span>
              <input className={inputClass} value={it.label} onChange={(e) => set(i, { label: e.target.value })} />
            </label>
            <label>
              <span className="visually-hidden">Kind</span>
              <select className={inputClass} value={it.kind} onChange={(e) => set(i, { kind: e.target.value as Item["kind"], target: e.target.value === "provider" ? "destination" : e.target.value === "field" ? "member_id" : "referral_form" })}>
                <option value="field">Detail</option>
                <option value="document">Document</option>
                <option value="provider">Destination</option>
              </select>
            </label>
            <label>
              <span className="visually-hidden">What</span>
              {it.kind === "provider" ? (
                <input className={inputClass} value="Accepting specialist" readOnly />
              ) : (
                <select className={inputClass} value={it.target} onChange={(e) => set(i, { target: e.target.value })}>
                  {Object.entries(it.kind === "field" ? FIELD_LABEL : DOCS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              )}
            </label>
            <label style={{ display: "flex", gap: 6, alignItems: "center", whiteSpace: "nowrap" }}>
              <input type="checkbox" checked={it.blocking} onChange={(e) => set(i, { blocking: e.target.checked })} /> Required
            </label>
            <Button size="sm" variant="quiet" onClick={() => setItems((l) => l.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </li>
        ))}
      </ul>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Button size="sm" onClick={() => setItems((l) => [...l, { label: "New item", kind: "document", target: "clinical_note", blocking: false }])}>
          Add item
        </Button>
        <Button size="sm" variant="primary" onClick={save}>
          Save checklist
        </Button>
        <Button size="sm" variant="quiet" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export function Checklists() {
  const toast = useToast();
  const { data, mutate } = useApi<Checklist[]>("/checklists");
  const [editing, setEditing] = useState<string | null>(null);
  if (!data) return <Skeleton lines={6} />;

  async function reset(specialty: string) {
    await api.del(`/checklists/${specialty}`);
    toast("Back to the standard checklist.");
    mutate();
  }

  return (
    <div className={styles.stack}>
      <p className={styles.muted}>Administrative completeness only. These rules never decide clinical need or urgency.</p>
      {data.map((c) => (
        <Panel
          key={c.specialty}
          title={label(SPECIALTY_LABEL, c.specialty)}
          actions={
            <>
              {c.customized ? <Tag tone="route">Customized, {c.version}</Tag> : <Tag>Standard</Tag>}
              {editing !== c.specialty && (
                <Button size="sm" onClick={() => setEditing(c.specialty)}>
                  Edit
                </Button>
              )}
              {c.customized && (
                <Button size="sm" variant="quiet" onClick={() => reset(c.specialty)}>
                  Use standard
                </Button>
              )}
            </>
          }
        >
          {editing === c.specialty ? (
            <EditChecklist
              c={c}
              onDone={() => {
                setEditing(null);
                mutate();
              }}
            />
          ) : (
            <p className={styles.muted}>
              {c.items.map((i) => `${String(i.label)}${i.blocking ? "" : " (optional)"}`).join(", ")}
            </p>
          )}
        </Panel>
      ))}
    </div>
  );
}
