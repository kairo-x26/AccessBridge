"use client";

import { useState, type FormEvent } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, inputClass } from "@/components/ui/Field";
import { Skeleton } from "@/components/ui/States";
import tableStyles from "@/components/ui/Table.module.css";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Provider } from "@/lib/api";
import { SPECIALTY_LABEL, label } from "@/lib/format";
import { useApi } from "@/lib/hooks";

export function Destinations() {
  const toast = useToast();
  const { data, mutate } = useApi<Provider[]>("/providers");
  const [editing, setEditing] = useState<Provider | "new" | null>(null);
  if (!data) return <Skeleton lines={6} />;
  const current = editing && editing !== "new" ? editing : null;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const body = {
      name: String(f.get("name")),
      specialty: String(f.get("specialty")),
      network_reference: String(f.get("network_reference") || "") || null,
      phone: String(f.get("phone") || "") || null,
      location: String(f.get("location") || "") || null,
      contact_method: String(f.get("contact_method")),
      accepts_referrals: f.get("accepts_referrals") === "on",
      languages: String(f.get("languages") || "").split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (current) await api.put(`/providers/${current.id}`, body);
      else await api.post("/providers", body);
      toast("Saved.");
      setEditing(null);
      mutate();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not saved.", "error");
    }
  }

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Button variant="primary" onClick={() => setEditing("new")}>
          Add a specialist office
        </Button>
      </div>
      <div className={tableStyles.wrap}>
        <table className={tableStyles.table}>
          <thead>
            <tr>
              <th scope="col">Office</th>
              <th scope="col">Specialty</th>
              <th scope="col">Sends by</th>
              <th scope="col">Phone</th>
              <th scope="col">Status</th>
              <th scope="col"><span className="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {data.map((p) => (
              <tr key={p.id}>
                <td className={tableStyles.primaryCell}>
                  {p.name}
                  <span className={tableStyles.sub}>{p.network_reference ?? "No network ID"}</span>
                </td>
                <td>{label(SPECIALTY_LABEL, p.specialty)}</td>
                <td>{p.contact_method === "direct" ? "Secure exchange" : p.contact_method === "fhir" ? "EHR (FHIR)" : "Fax"}</td>
                <td>{p.phone ?? "—"}</td>
                <td>{p.accepts_referrals ? <Tag tone="verified">Accepting</Tag> : <Tag tone="closed">Not accepting</Tag>}</td>
                <td>
                  <Button size="sm" variant="quiet" onClick={() => setEditing(p)}>
                    Edit
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Dialog open={!!editing} onClose={() => setEditing(null)} title={current ? `Edit ${current.name}` : "Add a specialist office"}>
        <form onSubmit={save} style={{ display: "grid", gap: 12 }} key={current?.id ?? "new"}>
          <Field label="Office name">{(p) => <input {...p} name="name" className={inputClass} defaultValue={current?.name} required />}</Field>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Field label="Specialty">
              {(p) => (
                <select {...p} name="specialty" className={inputClass} defaultValue={current?.specialty ?? "cardiology"}>
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
            <Field label="Sends by">
              {(p) => (
                <select {...p} name="contact_method" className={inputClass} defaultValue={current?.contact_method ?? "direct"}>
                  <option value="direct">Secure exchange</option>
                  <option value="fhir">EHR (FHIR)</option>
                  <option value="fax">Fax</option>
                </select>
              )}
            </Field>
            <Field label="Network ID">{(p) => <input {...p} name="network_reference" className={inputClass} defaultValue={current?.network_reference ?? ""} />}</Field>
            <Field label="Phone">{(p) => <input {...p} name="phone" className={inputClass} defaultValue={current?.phone ?? ""} />}</Field>
          </div>
          <Field label="Location">{(p) => <input {...p} name="location" className={inputClass} defaultValue={current?.location ?? ""} />}</Field>
          <Field label="Languages spoken" hint="Comma-separated codes, e.g. en, es">
            {(p) => <input {...p} name="languages" className={inputClass} defaultValue={current?.languages.join(", ") ?? ""} />}
          </Field>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="checkbox" name="accepts_referrals" defaultChecked={current?.accepts_referrals ?? true} /> Accepting new referrals
          </label>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
            <Button type="submit" variant="primary">
              Save office
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
