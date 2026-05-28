"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api";

/** Approve or reject an agent proposal. Rejection always asks why. */
export function ApprovalActions({
  approvalId,
  onDone,
  compact = false,
}: {
  approvalId: string;
  onDone: () => void;
  compact?: boolean;
}) {
  const toast = useToast();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"approved" | "rejected" | null>(null);

  async function decide(decision: "approved" | "rejected") {
    setBusy(decision);
    try {
      await api.post(`/approvals/${approvalId}/decision`, { decision, reason: reason || undefined });
      toast(decision === "approved" ? "Approved. The agent will carry it out now." : "Rejected. Nothing was done.");
      onDone();
      setTimeout(onDone, 1500);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "That didn't go through.", "error");
    } finally {
      setBusy(null);
    }
  }

  if (rejecting) {
    return (
      <div style={{ display: "grid", gap: 8 }}>
        <label>
          <span className="visually-hidden">Reason for rejecting</span>
          <input
            className={inputClass}
            placeholder="Why not? (required)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            autoFocus
          />
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <Button size="sm" variant="danger" disabled={reason.trim().length < 3} busy={busy === "rejected"} onClick={() => decide("rejected")}>
            Reject proposal
          </Button>
          <Button size="sm" variant="quiet" onClick={() => setRejecting(false)}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      <Button size={compact ? "sm" : "md"} variant="primary" busy={busy === "approved"} onClick={() => decide("approved")}>
        Approve
      </Button>
      <Button size={compact ? "sm" : "md"} onClick={() => setRejecting(true)}>
        Reject
      </Button>
    </div>
  );
}
