import { NextResponse } from "next/server";

import { backendUrl, sessionCookie } from "@/lib/server/backend";

/** Second sign-in step: redeem the MFA challenge with a current TOTP code. */
export async function POST(request: Request) {
  const res = await fetch(backendUrl("v1/auth/mfa/verify"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  const data = await res.json();
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  const out = NextResponse.json({ ok: true });
  out.cookies.set(sessionCookie(data.access_token));
  return out;
}
