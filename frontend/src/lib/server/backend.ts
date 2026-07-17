import "server-only";

export const SESSION_COOKIE = "ab_session";
export const SESSION_MAX_AGE = 30 * 60; // matches backend access token lifetime

export function backendUrl(path: string): URL {
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  return new URL(path.replace(/^\/+/, ""), base.endsWith("/") ? base : `${base}/`);
}

export function sessionCookie(token: string) {
  return {
    name: SESSION_COOKIE,
    value: token,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "strict" as const,
    path: "/",
    maxAge: SESSION_MAX_AGE,
  };
}

/** Headers that let the API rate-limit per browser rather than per BFF instance. */
export function forwardedHeaders(request: Request): Record<string, string> {
  const ip = request.headers.get("x-forwarded-for");
  return ip ? { "x-forwarded-for": ip.split(",")[0].trim() } : {};
}
