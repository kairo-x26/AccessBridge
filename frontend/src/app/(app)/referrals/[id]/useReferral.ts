"use client";

import { useSWRConfig } from "swr";

import type { PendingApproval, ReferralDetail } from "@/lib/api";
import { useApi } from "@/lib/hooks";

/** The referral plus a refresh that revalidates every view of it on the page. */
export function useReferral(id: string) {
  const detail = useApi<ReferralDetail>(`/referrals/${id}`);
  const approvals = useApi<PendingApproval[]>("/approvals");
  const { mutate } = useSWRConfig();
  const refresh = () =>
    mutate((key) => typeof key === "string" && (key.includes(id) || key.startsWith("/approvals") || key.startsWith("/tasks")));
  const pending = (approvals.data ?? []).filter((a) => a.referral_id === id);
  return { ...detail, pending, refresh };
}
