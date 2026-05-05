import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, backendUrl, sessionCookie } from "@/lib/server/backend";

const PASS_REQUEST = ["content-type", "idempotency-key", "x-request-id"];
const PASS_RESPONSE = [
  "content-type",
  "content-disposition",
  "cache-control",
  "idempotent-replay",
  "x-request-id",
];
// Endpoints that issue a new access token (e.g. after enabling MFA).
const TOKEN_ISSUING = new Set(["auth/mfa/enable"]);

async function forward(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const joined = path.map(encodeURIComponent).join("/");
  if (joined.startsWith("webhooks/") || joined.startsWith("auth/login")) {
    return NextResponse.json({ error: { message: "Not available through this route." } }, {
      status: 404,
    });
  }
  const target = backendUrl(`v1/${joined}`);
  target.search = new URL(request.url).search;

  const headers = new Headers();
  for (const h of PASS_REQUEST) {
    const v = request.headers.get(h);
    if (v) headers.set(h, v);
  }
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (token) headers.set("authorization", `Bearer ${token}`);

  const hasBody = !["GET", "HEAD"].includes(request.method);
  let res: Response;
  try {
    res = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json(
      { error: { code: "backend_unavailable", message: "The AccessBridge service is unreachable. Try again shortly." } },
      { status: 502 },
    );
  }

  const outHeaders = new Headers();
  for (const h of PASS_RESPONSE) {
    const v = res.headers.get(h);
    if (v) outHeaders.set(h, v);
  }

  if (TOKEN_ISSUING.has(joined) && res.ok) {
    const data = await res.json();
    const out = NextResponse.json({ ok: true }, { status: res.status });
    if (data.access_token) out.cookies.set(sessionCookie(data.access_token));
    return out;
  }
  const out = new NextResponse(res.status === 204 ? null : res.body, {
    status: res.status,
    headers: outHeaders,
  });
  if (res.status === 401) out.cookies.delete(SESSION_COOKIE);
  return out;
}

export const GET = forward;
export const POST = forward;
export const PUT = forward;
export const PATCH = forward;
export const DELETE = forward;
