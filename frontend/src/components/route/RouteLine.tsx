import { ROUTE, STATUS_LABEL, type Status } from "@/lib/format";

import styles from "./RouteLine.module.css";

const OFF_ROUTE = new Set<Status>(["exception", "declined", "cancelled"]);

export function routeIndex(status: string): number {
  return ROUTE.findIndex((r) => r.status === status);
}

function describe(status: Status, reached: number): string {
  const stop = ROUTE[reached]?.short ?? "Imported";
  if (status === "exception") return `Exception after ${stop.toLowerCase()} (stop ${reached + 1} of 7)`;
  if (status === "declined" || status === "cancelled")
    return `${STATUS_LABEL[status]} after ${stop.toLowerCase()}`;
  if (status === "completed") return "Care completed (7 of 7)";
  return `${STATUS_LABEL[status]} (stop ${reached + 1} of 7)`;
}

/**
 * Compact transit-line view of a referral's progress, used in queue rows.
 * Stops passed are solid teal; the current stop is a ring; an exception branches off in amber
 * below the stop where it happened; a closed referral ends with a bar.
 */
export function RouteLine({
  status,
  progress,
  width = 168,
}: {
  status: string;
  progress?: string;
  width?: number;
}) {
  const s = status as Status;
  const off = OFF_ROUTE.has(s);
  const reached = Math.max(0, routeIndex(off ? (progress ?? "imported") : s));
  const pad = 7;
  const y = 9;
  const step = (width - pad * 2) / (ROUTE.length - 1);
  const x = (i: number) => pad + i * step;
  const closed = s === "declined" || s === "cancelled";

  return (
    <svg
      className={styles.mini}
      width={width}
      height={22}
      viewBox={`0 0 ${width} 22`}
      role="img"
      aria-label={describe(s, reached)}
    >
      <title>{describe(s, reached)}</title>
      {ROUTE.slice(1).map((_, i) => {
        const done = i + 1 <= reached;
        return (
          <line
            key={`seg-${i}`}
            x1={x(i)}
            x2={x(i + 1)}
            y1={y}
            y2={y}
            className={done ? styles.segDone : closed ? styles.segClosed : styles.segAhead}
          />
        );
      })}
      {ROUTE.map((stop, i) => {
        if (i < reached) return <circle key={stop.status} cx={x(i)} cy={y} r={3.2} className={styles.stopDone} />;
        if (i > reached)
          return <circle key={stop.status} cx={x(i)} cy={y} r={2.6} className={closed ? styles.stopClosed : styles.stopAhead} />;
        if (s === "completed") return <circle key={stop.status} cx={x(i)} cy={y} r={5} className={styles.stopComplete} />;
        if (s === "exception")
          return (
            <g key={stop.status}>
              <line x1={x(i)} x2={x(i)} y1={y} y2={y + 11} className={styles.branch} />
              <rect
                x={x(i) - 4.2}
                y={y - 4.2}
                width={8.4}
                height={8.4}
                transform={`rotate(45 ${x(i)} ${y})`}
                className={styles.stopException}
              />
            </g>
          );
        if (closed)
          return (
            <g key={stop.status}>
              <circle cx={x(i)} cy={y} r={3.2} className={styles.stopDone} />
              <line x1={x(i) + 5} x2={x(i) + 5} y1={y - 6} y2={y + 6} className={styles.endBar} />
            </g>
          );
        return (
          <g key={stop.status}>
            <circle cx={x(i)} cy={y} r={5.4} className={styles.stopCurrentRing} />
            <circle cx={x(i)} cy={y} r={2.2} className={styles.stopDone} />
          </g>
        );
      })}
    </svg>
  );
}
