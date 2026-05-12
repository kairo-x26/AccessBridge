"use client";

import { useEffect, useRef, type ReactNode } from "react";

import styles from "./Dialog.module.css";

/** Modal built on the native <dialog>, which handles focus trapping and Escape. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      className={styles.dialog}
      aria-labelledby="dialog-title"
      onClose={onClose}
      onCancel={onClose}
    >
      <header className={styles.header}>
        <h2 id="dialog-title">{title}</h2>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>
      <div className={styles.body}>{children}</div>
      {footer && <footer className={styles.footer}>{footer}</footer>}
    </dialog>
  );
}
