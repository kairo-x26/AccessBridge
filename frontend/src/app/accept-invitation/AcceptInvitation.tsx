"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { BrandMark } from "@/components/app/Brand";
import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";

import styles from "../login/login.module.css";

export function AcceptInvitation() {
  const token = useSearchParams().get("token") ?? "";
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [done, setDone] = useState<{ org: string; email: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (f.get("password") !== f.get("confirm")) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    setError(null);
    setProblems([]);
    const res = await fetch("/api/v1/auth/accept-invitation", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token, full_name: f.get("full_name"), password: f.get("password") }),
    });
    const body = await res.json();
    setBusy(false);
    if (!res.ok) {
      setError(body?.error?.message ?? "This invitation couldn't be used.");
      setProblems(body?.error?.details?.problems ?? []);
      return;
    }
    setDone({ org: body.organization_name, email: body.email });
  }

  return (
    <div className={styles.page}>
      <main id="main" className={styles.card}>
        <div className={styles.brand}>
          <BrandMark size={36} />
          <span className={styles.wordmark}>AccessBridge</span>
        </div>
        {done ? (
          <div className={styles.form}>
            <h1 className={styles.title}>You&rsquo;re in</h1>
            <p className={styles.help}>
              Your account for {done.org} is ready. Sign in as {done.email}.
            </p>
            <Link href="/login">Go to sign in</Link>
          </div>
        ) : !token ? (
          <Notice tone="error" title="This link is incomplete">
            Ask your administrator to send the invitation again.
          </Notice>
        ) : (
          <form className={styles.form} onSubmit={submit}>
            <h1 className={styles.title}>Join your team</h1>
            {error && (
              <Notice tone="error" title={error}>
                {problems.length > 0 && (
                  <ul>
                    {problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
              </Notice>
            )}
            <Field label="Your full name">{(p) => <input {...p} name="full_name" className={inputClass} autoComplete="name" required />}</Field>
            <Field label="Choose a password" hint="At least 12 characters with upper- and lower-case letters and a number.">
              {(p) => <input {...p} name="password" type="password" className={inputClass} autoComplete="new-password" required minLength={12} />}
            </Field>
            <Field label="Confirm password">
              {(p) => <input {...p} name="confirm" type="password" className={inputClass} autoComplete="new-password" required />}
            </Field>
            <Button type="submit" variant="primary" busy={busy}>
              Create my account
            </Button>
          </form>
        )}
      </main>
    </div>
  );
}
