"use client";

import {
  BookOpenText,
  CircleCheckBig,
  Gauge,
  ListTodo,
  LogOut,
  MessageSquareText,
  Route,
  Settings,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import type { Notification, PendingApproval } from "@/lib/api";
import { ROLE_LABEL } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import { BrandMark } from "./Brand";
import { NotificationsMenu } from "./NotificationsMenu";
import styles from "./AppShell.module.css";

type NavItem = { href: string; label: string; icon: ReactNode; perm: string | string[]; count?: number };

function Rail() {
  const pathname = usePathname();
  const { data: me } = useMe();
  const { data: approvals } = useApi<PendingApproval[]>(
    can(me, "referral:read") ? "/approvals" : null,
    { refreshInterval: 30_000 },
  );

  const items: NavItem[] = [
    { href: "/queue", label: "Referrals", icon: <Route />, perm: "referral:read" },
    { href: "/approvals", label: "Approvals", icon: <CircleCheckBig />, perm: "action:approve", count: approvals?.length },
    { href: "/tasks", label: "Tasks", icon: <ListTodo />, perm: "task:read" },
    { href: "/inbox", label: "Replies", icon: <MessageSquareText />, perm: "message:read" },
    { href: "/dashboard", label: "Dashboard", icon: <Gauge />, perm: "report:read" },
    { href: "/policies", label: "Policies", icon: <BookOpenText />, perm: "policy:search" },
    { href: "/audit", label: "Audit", icon: <ShieldCheck />, perm: "audit:read" },
    { href: "/admin", label: "Admin", icon: <Settings />, perm: ["user:manage", "config:manage", "template:manage"] },
  ];
  const visible = items.filter((i) => (Array.isArray(i.perm) ? i.perm.some((p) => can(me, p)) : can(me, i.perm)));

  return (
    <ul className={styles.nav}>
      {visible.map((item) => {
        const active =
          pathname === item.href ||
          pathname.startsWith(`${item.href}/`) ||
          (item.href === "/queue" && pathname.startsWith("/referrals"));
        return (
          <li key={item.href}>
            <Link href={item.href} className={styles.navItem} aria-current={active ? "page" : undefined}>
              <span className={styles.navIcon} aria-hidden="true">
                {item.icon}
                {!!item.count && <span className={styles.count}>{item.count > 99 ? "99+" : item.count}</span>}
              </span>
              <span className={styles.navLabel}>
                {item.label}
                {!!item.count && <span className="visually-hidden"> ({item.count} waiting)</span>}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function MfaBanner() {
  const pathname = usePathname();
  const { data: me } = useMe();
  if (!me?.mfa_required || me.mfa_satisfied || pathname === "/account") return null;
  return (
    <div className={styles.banner} role="alert">
      Your organization requires two-step verification. <Link href="/account">Set it up now</Link> to keep working.
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: me } = useMe();
  const { data: notes } = useApi<Notification[]>(me ? "/notifications" : null, { refreshInterval: 60_000 });

  async function signOut() {
    await fetch("/api/session", { method: "DELETE" });
    router.replace("/login");
  }

  return (
    <div className={styles.shell}>
      <nav className={styles.rail} aria-label="Main">
        <Link href="/queue" className={styles.brand} aria-label="AccessBridge home">
          <BrandMark />
        </Link>
        <Suspense fallback={<ul className={styles.nav} />}>
          <Rail />
        </Suspense>
      </nav>
      <div className={styles.main}>
        <header className={styles.topbar}>
          <p className={styles.org}>{me?.organization_name ?? "\u00a0"}</p>
          <div className={styles.user}>
            <NotificationsMenu notes={notes ?? []} />
            {me && (
              <Link href="/account" className={styles.me}>
                <span className={styles.meName}>{me.full_name}</span>
                <span className={styles.meRole}>{ROLE_LABEL[me.role] ?? me.role}</span>
              </Link>
            )}
            <button type="button" className={styles.signOut} onClick={signOut}>
              <LogOut aria-hidden="true" size={18} />
              <span>Sign out</span>
            </button>
          </div>
        </header>
        <Suspense>
          <MfaBanner />
        </Suspense>
        <main id="main" className={styles.content} tabIndex={-1}>
          {children}
        </main>
      </div>
    </div>
  );
}
