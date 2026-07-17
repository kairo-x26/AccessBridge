import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, backendUrl, forwardedHeaders, sessionCookie } from "@/lib/server/backend";

/** Sign in: exchange credentials for a backend token kept in an httpOnly cookie. */
export async function POST(request: Request) {
  const body = await request.text();
  const res = await fetch(backendUrl("v1/auth/login"), {
    method: "POST",
    headers: { "content-type": "application/json", ...forwardedHeaders(request) },
    body,
    cache: "no-store",
  });
  const data = await res.json();
  if (!res.ok) return NextResponse.json(data, { status: res.status });
  if (data.mfa_required) {
    return NextResponse.json({ mfa_required: true, challenge: data.mfa_challenge });
  }
  const out = NextResponse.json({ ok: true });
  out.cookies.set(sessionCookie(data.access_token));
  return out;
}

/** Sign out. */
export async function DELETE() {
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  return new NextResponse(null, { status: 204 });
}
