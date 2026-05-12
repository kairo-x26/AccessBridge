"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import styles from "./Toast.module.css";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; message: string };
const Ctx = createContext<(message: string, tone?: Tone) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Tone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className={styles.region} aria-live="polite" aria-atomic="false">
        {toasts.map((t) => (
          <div key={t.id} className={`${styles.toast} ${styles[t.tone]}`} role={t.tone === "error" ? "alert" : "status"}>
            {t.message}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
