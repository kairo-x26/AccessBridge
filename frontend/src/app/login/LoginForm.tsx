"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { BrandMark } from "@/components/app/Brand";
import { RouteLine } from "@/components/route/RouteLine";
import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";

import styles from "./login.module.css";

const DEMO = process.env.NEXT_PUBLIC_DEMO === "1";

export function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function go() {
    router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/queue");
  }

  async function submitPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          organization: String(form.get("organization")).trim(),
          email: String(form.get("email")).trim(),
          password: String(form.get("password")),
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data?.error?.message ?? "Check your organization, email and password.");
      } else if (data.mfa_required) {
        setChallenge(data.challenge);
        setStep("mfa");
      } else {
        go();
      }
    } catch {
      setError("AccessBridge is unreachable. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code")).replace(/\s/g, "");
    setBusy(true);
    setError(null);
    const res = await fetch("/api/session/mfa", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ challenge, code }),
    });
    setBusy(false);
    if (res.ok) go();
    else setError((await res.json())?.error?.message ?? "That code didn't match.");
  }

  return (
    <div className={styles.page}>
      <main id="main" className={styles.card}>
        <div className={styles.brand}>
          <BrandMark size={36} />
          <span className={styles.wordmark}>AccessBridge</span>
        </div>
        <div className={styles.route} aria-hidden="true">
          <RouteLine status="scheduled" width={300} />
          <p className={styles.routeCaption}>From referral to completed care, with evidence at every stop.</p>
        </div>

        {step === "password" ? (
          <form className={styles.form} onSubmit={submitPassword} noValidate>
            <h1 className={styles.title}>Sign in</h1>
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Organization" hint="Your clinic's short name, for example riverbend.">
              {(p) => (
                <input {...p} name="organization" className={inputClass} autoComplete="organization" required defaultValue={DEMO ? "riverbend" : undefined} />
              )}
            </Field>
            <Field label="Email">
              {(p) => <input {...p} name="email" type="email" className={inputClass} autoComplete="username" required />}
            </Field>
            <Field label="Password">
              {(p) => (
                <input {...p} name="password" type="password" className={inputClass} autoComplete="current-password" required />
              )}
            </Field>
            <Button type="submit" variant="primary" busy={busy}>
              Sign in
            </Button>
          </form>
        ) : (
          <form className={styles.form} onSubmit={submitCode} noValidate>
            <h1 className={styles.title}>Enter your verification code</h1>
            <p className={styles.help}>Open your authenticator app and enter the 6-digit code for AccessBridge.</p>
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Verification code">
              {(p) => (
                <input {...p} name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} className={inputClass} required autoFocus />
              )}
            </Field>
            <Button type="submit" variant="primary" busy={busy}>
              Verify and continue
            </Button>
            <button type="button" className={styles.link} onClick={() => setStep("password")}>
              Use a different account
            </button>
          </form>
        )}

        {DEMO && step === "password" && (
          <details className={styles.demo}>
            <summary>Demo accounts</summary>
            <p>
              Organization <code>riverbend</code>, password <code>Demo-Password-2026</code>. Try
              <code>priya.coordinator@riverbend.example.org</code>, <code>grace.navigator@…</code>,{" "}
              <code>dana.admin@…</code>, <code>amara.clinician@…</code> or <code>ivy.security@…</code>.
              All data is synthetic.
            </p>
          </details>
        )}
      </main>
    </div>
  );
}
