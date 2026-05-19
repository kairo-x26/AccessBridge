"use client";

import type { ReactNode } from "react";
import { SWRConfig } from "swr";

import { ToastProvider } from "@/components/ui/Toast";
import { fetcher } from "@/lib/api";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, shouldRetryOnError: false, dedupingInterval: 2000 }}>
      <ToastProvider>{children}</ToastProvider>
    </SWRConfig>
  );
}
