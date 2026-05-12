import type { ButtonHTMLAttributes, ReactNode } from "react";

import styles from "./Button.module.css";

type Variant = "primary" | "secondary" | "quiet" | "danger";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  busy?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  busy = false,
  icon,
  children,
  className,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={[styles.button, styles[variant], styles[size], className].filter(Boolean).join(" ")}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      {...rest}
    >
      {icon && <span className={styles.icon} aria-hidden="true">{icon}</span>}
      <span>{children}</span>
    </button>
  );
}
