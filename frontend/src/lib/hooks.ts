"use client";

import useSWR, { type SWRConfiguration } from "swr";

import { fetcher, type Me, type Staff } from "./api";

export function useApi<T>(path: string | null, config?: SWRConfiguration<T>) {
  return useSWR<T>(path, fetcher, { revalidateOnFocus: true, ...config });
}

export function useMe() {
  return useApi<Me>("/auth/me", { revalidateOnFocus: false });
}

export function useStaffNames() {
  const { data } = useApi<Staff[]>("/users/staff", { revalidateOnFocus: false });
  const names: Record<string, string> = {};
  for (const s of data ?? []) names[s.id] = s.full_name;
  return { staff: data ?? [], names };
}

export function can(me: Me | undefined, permission: string): boolean {
  return !!me?.permissions.includes(permission);
}
