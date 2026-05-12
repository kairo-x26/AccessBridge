import type { ReactNode } from "react";

import styles from "./States.module.css";

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <p className={styles.emptyTitle}>{title}</p>
      {children && <p className={styles.emptyText}>{children}</p>}
      {action}
    </div>
  );
}

export function Skeleton({ lines = 3, label = "Loading" }: { lines?: number; label?: string }) {
  return (
    <div className={styles.skeleton} role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className={styles.bar} style={{ width: `${92 - i * 14}%` }} />
      ))}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: Error; retry?: () => void }) {
  return (
    <div className={styles.empty} role="alert">
      <p className={styles.emptyTitle}>This didn&rsquo;t load</p>
      <p className={styles.emptyText}>{error.message}</p>
      {retry && (
        <button type="button" className={styles.retry} onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
