"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { ApiError, api, type ReferralDetail } from "@/lib/api";
import { SPECIALTY_LABEL } from "@/lib/format";

type ImportResult = {
  imported: string[];
  duplicates: string[];
  exceptions: string[];
  errors: { row?: string; source_id?: string; error: string }[];
};

export function ImportDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const router = useRouter();
  const [mode, setMode] = useState<"csv" | "manual">("csv");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  function close() {
    setResult(null);
    setError(null);
    onClose();
  }

  async function uploadCsv(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const file = new FormData(e.currentTarget).get("file");
    if (!(file instanceof File) || !file.size) {
      setError("Choose a CSV file to import.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.upload<ImportResult>("/referrals/import/csv", file));
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function createManual(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body: Record<string, string> = {};
    for (const [k, v] of f.entries()) if (String(v).trim()) body[k] = String(v).trim();
    setBusy(true);
    setError(null);
    try {
      const created = await api.post<ReferralDetail>("/referrals", body);
      onDone();
      close();
      router.push(`/referrals/${created.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the referral.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={close} title="Add referrals">
      <div role="radiogroup" aria-label="How to add referrals" style={{ display: "flex", gap: 8 }}>
        <Button size="sm" variant={mode === "csv" ? "primary" : "secondary"} aria-pressed={mode === "csv"} onClick={() => setMode("csv")}>
          Import a CSV export
        </Button>
        <Button size="sm" variant={mode === "manual" ? "primary" : "secondary"} aria-pressed={mode === "manual"} onClick={() => setMode("manual")}>
          Enter one by hand
        </Button>
      </div>
      {error && <Notice tone="error">{error}</Notice>}

      {mode === "csv" ? (
        result ? (
          <>
            <Notice tone={result.errors.length ? "warning" : "success"} title={`${result.imported.length} imported`}>
              <ul>
                <li>{result.duplicates.length} already in AccessBridge (no new work created)</li>
                <li>{result.exceptions.length} need identity review</li>
                {result.errors.map((e, i) => (
                  <li key={i}>
                    Row {e.row ?? e.source_id}: {e.error}
                  </li>
                ))}
              </ul>
            </Notice>
            <Button onClick={() => setResult(null)}>Import another file</Button>
          </>
        ) : (
          <form onSubmit={uploadCsv} style={{ display: "grid", gap: 16 }}>
            <Field
              label="CSV file"
              hint="Columns: source_id, ehr_patient_id, given_name, family_name, specialty. Optional: birth_date (YYYY-MM-DD), phone, email, preferred_language, priority, reason, referring_clinician, provider_name."
            >
              {(p) => <input {...p} name="file" type="file" accept=".csv,text/csv" className={inputClass} />}
            </Field>
            <Button type="submit" variant="primary" busy={busy}>
              Import referrals
            </Button>
          </form>
        )
      ) : (
        <form onSubmit={createManual} style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Given name">{(p) => <input {...p} name="given_name" className={inputClass} required />}</Field>
            <Field label="Family name">{(p) => <input {...p} name="family_name" className={inputClass} required />}</Field>
            <Field label="MRN">{(p) => <input {...p} name="ehr_patient_id" className={inputClass} required />}</Field>
            <Field label="Date of birth">{(p) => <input {...p} name="birth_date" type="date" className={inputClass} />}</Field>
          </div>
          <Field label="Specialty">
            {(p) => (
              <select {...p} name="specialty" className={inputClass} required defaultValue="">
                <option value="" disabled>
                  Choose a specialty
                </option>
                {Object.entries(SPECIALTY_LABEL)
                  .filter(([k]) => !["unsupported", "unspecified"].includes(k))
                  .map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
              </select>
            )}
          </Field>
          <Field label="Reason for referral (as written by the clinician)">
            {(p) => <textarea {...p} name="reason_from_source" className={inputClass} />}
          </Field>
          <Field label="Paper or fax reference" hint="Optional. Used to spot duplicates.">
            {(p) => <input {...p} name="source_id" className={inputClass} />}
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            Create referral
          </Button>
        </form>
      )}
    </Dialog>
  );
}
