"use client";

import { useState, type FormEvent } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { Skeleton } from "@/components/ui/States";
import tableStyles from "@/components/ui/Table.module.css";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type UserRow } from "@/lib/api";
import { ROLE_LABEL, relative } from "@/lib/format";
import { useApi, useMe } from "@/lib/hooks";

import styles from "./admin.module.css";

type Invite = { invitation_id: string; expires_at: string; token: string };

export function People() {
  const toast = useToast();
  const { data: me } = useMe();
  const { data: users, mutate } = useApi<UserRow[]>("/users");
  const [invite, setInvite] = useState<Invite | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    try {
      setInvite(await api.post<Invite>("/users/invitations", { email: f.get("email"), role: f.get("role") }));
      e.currentTarget?.reset();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Invitation not sent.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function update(u: UserRow, body: Record<string, string>) {
    try {
      await api.patch(`/users/${u.id}`, body);
      toast("Saved.");
      mutate();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not saved.", "error");
    }
  }

  return (
    <div className={styles.stack}>
      <Panel title="Invite someone" description="They choose their own password. Invitations expire after 7 days.">
        <form onSubmit={send} className={styles.row}>
          <Field label="Email">{(p) => <input {...p} name="email" type="email" className={inputClass} required />}</Field>
          <Field label="Role">
            {(p) => (
              <select {...p} name="role" className={inputClass} defaultValue="coordinator">
                {Object.entries(ROLE_LABEL).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Button type="submit" variant="primary" busy={busy}>
            Create invitation
          </Button>
        </form>
        {invite && (
          <div style={{ marginTop: 16 }}>
            <Notice tone="success" title="Invitation created">
              Send this invitation link to the person securely. It works once and expires {relative(invite.expires_at)}.
            </Notice>
            <p className={styles.token}>
              {typeof window !== "undefined" ? window.location.origin : ""}/accept-invitation?token={invite.token}
            </p>
          </div>
        )}
      </Panel>
      <Panel title="People">
        {!users ? (
          <Skeleton lines={5} />
        ) : (
          <div className={tableStyles.wrap}>
            <table className={tableStyles.table}>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Role</th>
                  <th scope="col">Two-step</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col">Access</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td className={tableStyles.primaryCell}>
                      {u.full_name}
                      <span className={tableStyles.sub}>{u.email}</span>
                    </td>
                    <td>
                      <label>
                        <span className="visually-hidden">Role for {u.full_name}</span>
                        <select className={inputClass} value={u.role} disabled={u.id === me?.id} onChange={(e) => update(u, { role: e.target.value })}>
                          {Object.entries(ROLE_LABEL).map(([k, v]) => (
                            <option key={k} value={k}>
                              {v}
                            </option>
                          ))}
                        </select>
                      </label>
                    </td>
                    <td>{u.mfa_enabled ? <Tag tone="verified">On</Tag> : <Tag>Off</Tag>}</td>
                    <td>{u.last_login_at ? relative(u.last_login_at) : "Never"}</td>
                    <td>
                      {u.id === me?.id ? (
                        <span className={styles.muted}>You</span>
                      ) : u.status === "active" ? (
                        <Button size="sm" variant="danger" onClick={() => update(u, { status: "disabled" })}>
                          Turn off access
                        </Button>
                      ) : (
                        <Button size="sm" onClick={() => update(u, { status: "active" })}>
                          Restore access
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
