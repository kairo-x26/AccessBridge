"use client";

import { useState } from "react";

import { Field, inputClass } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type ReferralDetail } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/format";
import { useStaffNames } from "@/lib/hooks";

export function OwnerPicker({
  referral,
  canEdit,
  onChange,
}: {
  referral: ReferralDetail;
  canEdit: boolean;
  onChange: () => void;
}) {
  const { staff } = useStaffNames();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const assignable = staff.filter((s) => ["coordinator", "navigator", "admin"].includes(s.role));

  if (!canEdit) return <p>Owner: {referral.owner_name ?? "Unassigned"}</p>;

  async function assign(value: string) {
    setBusy(true);
    try {
      await api.patch(`/referrals/${referral.id}`, {
        expected_version: referral.version,
        ...(value ? { owner_id: value } : { clear_owner: true }),
      });
      toast(value ? "Owner updated." : "Owner removed.");
      onChange();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't change the owner.", "error");
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Field label="Owner" hint="The person responsible for the next step.">
      {(p) => (
        <select {...p} className={inputClass} value={referral.owner_id ?? ""} disabled={busy} onChange={(e) => assign(e.target.value)}>
          <option value="">Unassigned</option>
          {assignable.map((s) => (
            <option key={s.id} value={s.id}>
              {s.full_name}, {ROLE_LABEL[s.role]?.toLowerCase()}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}
