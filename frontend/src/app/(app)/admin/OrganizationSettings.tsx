"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Schemas } from "@/lib/api";
import { useApi } from "@/lib/hooks";

import styles from "./admin.module.css";

type Org = Schemas["OrgOut"];

export function OrganizationSettings() {
  const toast = useToast();
  const { data: org, mutate } = useApi<Org>("/organization");
  const [busy, setBusy] = useState(false);
  if (!org) return <Skeleton lines={5} />;

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      await api.patch("/organization", {
        name: String(f.get("name")),
        require_mfa: f.get("require_mfa") === "on",
        retention_days: Number(f.get("retention_years")) * 365,
        export_min_cell: Number(f.get("export_min_cell")),
        preauthorized_reminders: f.getAll("reminders").map(String),
      });
      toast("Organization settings saved.");
      mutate();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not saved.", "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={save} className={styles.stack}>
      <Panel title="Organization">
        <div className={styles.row}>
          <Field label="Name">{(p) => <input {...p} name="name" className={inputClass} defaultValue={org.name} required />}</Field>
          <Field label="Sign-in name" hint="Staff type this when they sign in.">
            {(p) => <input {...p} className={inputClass} value={org.slug} readOnly />}
          </Field>
        </div>
      </Panel>
      <Panel title="Security and privacy">
        <div className={styles.stack}>
          <fieldset className={styles.checks}>
            <legend>Sign-in</legend>
            <label>
              <input type="checkbox" name="require_mfa" defaultChecked={org.require_mfa} />
              Require two-step verification for everyone
            </label>
          </fieldset>
          <div className={styles.row}>
            <Field label="Keep closed referral records for (years)" hint="Legal holds override this.">
              {(p) => (
                <input {...p} name="retention_years" type="number" min={1} max={10} className={inputClass} defaultValue={Math.round(org.retention_days / 365)} />
              )}
            </Field>
            <Field label="Hide counts smaller than" hint="Applies to downloaded reports, so small groups can't identify a patient.">
              {(p) => <input {...p} name="export_min_cell" type="number" min={0} max={20} className={inputClass} defaultValue={org.export_min_cell} />}
            </Field>
          </div>
        </div>
      </Panel>
      <Panel title="Automation" description="What the agent may do without asking first.">
        <div className={styles.stack}>
          <Notice tone="agent">
            Sending referral packages, recording appointments and closing referrals always need a person&rsquo;s approval. Only reviewed reminder texts can be pre-approved.
          </Notice>
          <fieldset className={styles.checks}>
            <legend>Reminders the agent may send on its own</legend>
            <label>
              <input type="checkbox" name="reminders" value="schedule_prompt" defaultChecked={org.preauthorized_reminders.includes("schedule_prompt")} />
              Ask the patient to schedule, once the specialist has the referral
            </label>
            <label>
              <input type="checkbox" name="reminders" value="appointment_check" defaultChecked={org.preauthorized_reminders.includes("appointment_check")} />
              Ask whether the visit happened, after the appointment date
            </label>
          </fieldset>
        </div>
      </Panel>
      <div>
        <Button type="submit" variant="primary" busy={busy}>
          Save settings
        </Button>
      </div>
    </form>
  );
}
