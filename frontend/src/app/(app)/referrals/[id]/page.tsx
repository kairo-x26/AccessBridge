import type { Metadata } from "next";
import { Suspense } from "react";

import { Skeleton } from "@/components/ui/States";

import { ReferralView } from "./ReferralView";

export const metadata: Metadata = { title: "Referral" };

export default function ReferralPage({ params }: PageProps<"/referrals/[id]">) {
  return (
    <Suspense fallback={<Skeleton lines={8} label="Loading referral" />}>
      {params.then(({ id }) => (
        <ReferralView id={id} />
      ))}
    </Suspense>
  );
}
