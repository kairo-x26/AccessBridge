"use client";

import { Check } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Field } from "@/lib/api";

import styles from "./referral.module.css";

function confidenceWord(c: number) {
  return c >= 0.9 ? "high confidence" : c >= 0.6 ? "medium confidence" : "low confidence, check carefully";
}

/**
 * One administrative detail and the candidates read from documents. Unconfirmed values are
 * drawn dashed violet (proposed); confirmed or corrected values are solid with a check.
 */
export function FieldRow({
  label,
  fields,
  docName,
  editable,
  onShow,
  onChange,
}: {
  label: string;
  fields: Field[];
  docName: (id: string) => string;
  editable: boolean;
  onShow: (f: Field) => void;
  onChange: () => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const live = fields.filter((f) => f.status !== "rejected");
  const shown = live.length ? live : fields;

  async function review(f: Field, action: "accept" | "correct" | "reject") {
    try {
      await api.patch(`/fields/${f.id}`, { action, corrected_value: action === "correct" ? value : undefined });
      setEditing(null);
      onChange();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't save that.", "error");
    }
  }

  return (
    <li className={styles.fieldRow}>
      <div className={styles.fieldLabel}>
        {label}
        {fields.some((f) => f.critical) && <span className={styles.muted}>Must confirm</span>}
      </div>
      <ul className={styles.candidates}>
        {shown.map((f) => {
          const verified = f.status === "accepted" || f.status === "corrected";
          return (
            <li key={f.id} className={`${styles.candidate} ${verified ? styles.verified : f.status === "rejected" ? styles.rejected : styles.proposed}`}>
              <div className={styles.candidateValue}>
                {verified && <Check aria-hidden="true" size={16} />}
                <span>{f.effective_value ?? f.value}</span>
                {f.status === "corrected" && <span className={styles.muted}>was “{f.value}”</span>}
              </div>
              <div className={styles.candidateMeta}>
                {verified ? (
                  <span>{f.status === "corrected" ? "Corrected" : "Confirmed"} by staff</span>
                ) : f.status === "rejected" ? (
                  <span>Rejected</span>
                ) : (
                  <span>
                    {f.method === "llm" ? "Read by the agent" : "Read from the form"}, {confidenceWord(f.confidence)}
                  </span>
                )}
                <button type="button" className={styles.linkButton} onClick={() => onShow(f)}>
                  Show in {docName(f.document_id)}
                </button>
              </div>
              {editable && editing === f.id ? (
                <div className={styles.inlineEdit}>
                  <label>
                    <span className="visually-hidden">Correct value for {label}</span>
                    <input className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
                  </label>
                  <Button size="sm" variant="primary" disabled={!value.trim()} onClick={() => review(f, "correct")}>
                    Save correction
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => setEditing(null)}>
                    Cancel
                  </Button>
                </div>
              ) : (
                editable &&
                f.status !== "rejected" && (
                  <div className={styles.candidateActions}>
                    {!verified && (
                      <Button size="sm" onClick={() => review(f, "accept")}>
                        Confirm
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="quiet"
                      onClick={() => {
                        setValue(f.effective_value ?? f.value);
                        setEditing(f.id);
                      }}
                    >
                      Correct
                    </Button>
                    <Button size="sm" variant="quiet" onClick={() => review(f, "reject")}>
                      Reject
                    </Button>
                  </div>
                )
              )}
            </li>
          );
        })}
      </ul>
    </li>
  );
}
