import type { components } from "./api-schema";

export type Schemas = components["schemas"];
export type ReferralSummary = Schemas["ReferralSummary"];
export type ReferralDetail = Schemas["ReferralDetail"];
export type StatusEvent = Schemas["StatusEventOut"];
export type Task = Schemas["TaskOut"];
export type DocumentInfo = Schemas["DocumentOut"];
export type Field = Schemas["FieldOut"];
export type Issue = Schemas["IssueOut"];
export type Validation = Schemas["ValidationOut"];
export type RunOut = Schemas["RunOut"];
export type RunDetail = Schemas["RunDetail"];
export type Action = Schemas["ActionOut"];
export type PendingApproval = Schemas["PendingApproval"];
export type Me = Schemas["MeOut"];
export type Provider = Schemas["ProviderOut"];
export type Communication = Schemas["CommunicationOut"];
export type InboxItem = Schemas["InboxItem"];
export type Template = Schemas["TemplateOut"];
export type AuditItem = Schemas["AuditOut"];
export type Staff = Schemas["StaffOut"];
export type UserRow = Schemas["UserOut"];
export type Notification = Schemas["NotificationOut"];
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: Record<string, unknown> = {},
  ) {
    super(message);
  }

  /** Human-readable list of reasons attached by the backend, if any. */
  get reasons(): string[] {
    const d = this.details;
    for (const key of ["reasons", "problems"]) {
      const v = d[key];
      if (Array.isArray(v)) return v.map(String);
    }
    return [];
  }
}

const BASE = "/api/v1";

async function parse(res: Response): Promise<unknown> {
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") ?? "";
  return type.includes("application/json") ? res.json() : res.text();
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { credentials: "same-origin", ...init });
  const body = await parse(res);
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string; details?: Record<string, unknown> } })?.error;
    const fastapi = (body as { detail?: unknown })?.detail;
    const message =
      err?.message ??
      (Array.isArray(fastapi) ? "Some fields are invalid." : undefined) ??
      `Request failed (${res.status}).`;
    if (res.status === 401 && typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      // A full reload is deliberate: it drops every cached record from the expired session.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    }
    throw new ApiError(res.status, err?.code ?? "error", message, err?.details ?? {});
  }
  return body as T;
}

function json(method: string, body?: unknown, headers: HeadersInit = {}): RequestInit {
  return {
    method,
    headers: { "content-type": "application/json", ...headers },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, headers?: HeadersInit) =>
    request<T>(path, json("POST", body ?? {}, headers)),
  patch: <T>(path: string, body: unknown) => request<T>(path, json("PATCH", body)),
  put: <T>(path: string, body: unknown) => request<T>(path, json("PUT", body)),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, { method: "POST", body: form });
  },
};

export const fetcher = <T>(path: string) => request<T>(path);

export function newIdempotencyKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
