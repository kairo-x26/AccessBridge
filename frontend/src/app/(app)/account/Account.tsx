"use client";

import { useState, type FormEvent } from "react";
import { mutate } from "swr";

import { PageHeader } from "@/components/app/PageHeader";
import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import { ApiError, api } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/format";
import { useMe } from "@/lib/hooks";

import styles from "./account.module.css";

type Setup = { secret: string; otpauth_uri: string };

export function Account() {
  const { data: me } = useMe();
  const [setup, setSetup] = useState<Setup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function begin() {
    setError(null);
    try {
      setSetup(await api.post<Setup>("/auth/mfa/setup"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start setup.");
    }
  }

  async function confirm(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get("code")).replace(/\s/g, "");
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/mfa/enable", { code });
      setDone(true);
      setSetup(null);
      mutate("/auth/me");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That code didn't match.");
    } finally {
      setBusy(false);
    }
  }

  if (!me) return <Skeleton lines={5} />;
  return (
    <>
      <PageHeader title="Your account" />
      <div className={styles.grid}>
        <Panel title="Profile">
          <dl className={styles.facts}>
            <dt>Name</dt>
            <dd>{me.full_name}</dd>
            <dt>Email</dt>
            <dd>{me.email}</dd>
            <dt>Role</dt>
            <dd>{ROLE_LABEL[me.role] ?? me.role}</dd>
            <dt>Organization</dt>
            <dd>{me.organization_name}</dd>
          </dl>
        </Panel>
        <Panel
          title="Two-step verification"
          description="A code from an authenticator app is needed at every sign-in, in addition to your password."
        >
          {error && <Notice tone="error">{error}</Notice>}
          {done && <Notice tone="success">Two-step verification is on.</Notice>}
          {me.mfa_enabled ? (
            !done && <Notice tone="success">Two-step verification is on for your account.</Notice>
          ) : setup ? (
            <form onSubmit={confirm} className={styles.form}>
              <ol className={styles.steps}>
                <li>Open your authenticator app and add an account.</li>
                <li>
                  Enter this setup key: <code className={styles.key}>{setup.secret.match(/.{1,4}/g)?.join(" ")}</code>
                  <span className={styles.muted}>
                    {" "}
                    or open <a href={setup.otpauth_uri}>the setup link</a> on this device.
                  </span>
                </li>
                <li>Type the 6-digit code the app shows.</li>
              </ol>
              <Field label="Verification code">
                {(p) => <input {...p} name="code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className={inputClass} required />}
              </Field>
              <Button type="submit" variant="primary" busy={busy}>
                Turn on two-step verification
              </Button>
            </form>
          ) : (
            <Button variant="primary" onClick={begin}>
              Set up two-step verification
            </Button>
          )}
        </Panel>
      </div>
    </>
  );
}
