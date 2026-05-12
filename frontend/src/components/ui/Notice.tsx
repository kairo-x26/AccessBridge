import type { ReactNode } from "react";

import styles from "./Notice.module.css";

type Tone = "info" | "warning" | "error" | "success" | "agent";

export function Notice({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: Tone;
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className={`${styles.notice} ${styles[tone]}`} role={tone === "error" ? "alert" : "status"}>
      <div className={styles.body}>
        {title && <p className={styles.title}>{title}</p>}
        {children && <div className={styles.text}>{children}</div>}
      </div>
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
