"use client";

import { Bell } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { mutate } from "swr";

import { api, type Notification } from "@/lib/api";
import { relative } from "@/lib/format";

import styles from "./AppShell.module.css";

export function NotificationsMenu({ notes }: { notes: Notification[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const unread = notes.filter((n) => !n.read).length;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function read(id: string) {
    await api.post(`/notifications/${id}/read`);
    mutate("/notifications");
  }

  return (
    <div className={styles.notes} ref={ref}>
      <button
        type="button"
        className={styles.bell}
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
      >
        <Bell aria-hidden="true" size={20} />
        <span className="visually-hidden">Notifications{unread ? `, ${unread} unread` : ""}</span>
        {unread > 0 && <span className={styles.dot} aria-hidden="true" />}
      </button>
      {open && (
        <div className={styles.notesMenu}>
          <p className={styles.notesTitle}>Notifications</p>
          {notes.length === 0 && <p className={styles.notesEmpty}>Nothing new. Completed referrals show up here.</p>}
          <ul>
            {notes.slice(0, 8).map((n) => (
              <li key={n.id} className={n.read ? styles.noteRead : undefined}>
                {n.referral_id ? (
                  <Link href={`/referrals/${n.referral_id}`} onClick={() => read(n.id)}>
                    {n.message}
                  </Link>
                ) : (
                  <span>{n.message}</span>
                )}
                <span className={styles.noteTime}>{relative(n.created_at)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
