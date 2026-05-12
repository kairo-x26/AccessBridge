import type { ReactNode } from "react";

import styles from "./Panel.module.css";

export function Panel({
  title,
  description,
  actions,
  children,
  id,
  tone,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
  tone?: "agent";
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      className={`${styles.panel} ${tone === "agent" ? styles.agent : ""}`}
      aria-labelledby={headingId}
      id={id}
    >
      {(title || actions) && (
        <header className={styles.header}>
          <div>
            {title && (
              <h2 className={styles.title} id={headingId}>
                {title}
              </h2>
            )}
            {description && <p className={styles.description}>{description}</p>}
          </div>
          {actions && <div className={styles.actions}>{actions}</div>}
        </header>
      )}
      <div className={styles.body}>{children}</div>
    </section>
  );
}
