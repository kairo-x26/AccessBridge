"use client";

import { useId, useState, type ReactNode } from "react";

import styles from "./Charts.module.css";

/** The one number a view leads with. Proportional figures, same sans as everything. */
export function HeroFigure({ label, value, detail }: { label: string; value: string; detail?: ReactNode }) {
  return (
    <div className={styles.hero}>
      <p className={styles.heroLabel}>{label}</p>
      <p className={styles.heroValue}>{value}</p>
      {detail && <p className={styles.heroDetail}>{detail}</p>}
    </div>
  );
}

export function StatTile({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: "warning" }) {
  return (
    <div className={`${styles.tile} ${tone === "warning" ? styles.tileWarning : ""}`}>
      <p className={styles.tileLabel}>{label}</p>
      <p className={styles.tileValue}>{value}</p>
      {note && <p className={styles.tileNote}>{note}</p>}
    </div>
  );
}

/** Ratio against a whole; the track is a lighter step of the same ramp as the fill. */
export function Meter({ value, label }: { value: number | null; label: string }) {
  const pct = value == null ? 0 : Math.round(value * 100);
  return (
    <div className={styles.meter} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
      <span className={styles.meterTrack}>
        <span className={styles.meterFill} style={{ width: `${pct}%` }} />
      </span>
      <span className={styles.meterValue}>{value == null ? "—" : `${pct}%`}</span>
    </div>
  );
}

/** Smallest of 1, 2, 5 × 10^k (or 2× that for headroom) at or above the value; clean ticks. */
function niceCeil(v: number): number {
  const pow = 10 ** Math.floor(Math.log10(Math.max(1, v)));
  for (const m of [1, 2, 5, 10]) if (m * pow >= v) return m * pow;
  return 10 * pow;
}

type Datum = { key: string; label: string; value: number; color?: string };

/**
 * Vertical columns from one baseline. Thin (<=24px) with a 4px rounded data end. Each column
 * is focusable and shows the same readout on hover and keyboard focus; the value is also
 * printed on the cap and available in the table view.
 */
export function ColumnChart({ data, title, unit }: { data: Datum[]; title: string; unit: string }) {
  const id = useId();
  const [active, setActive] = useState<string | null>(null);
  const width = 520;
  const height = 210;
  const axis = 28;
  const top = 22;
  const max = Math.max(1, ...data.map((d) => d.value));
  const nice = niceCeil(max);
  const band = width / data.length;
  const bar = Math.min(24, band * 0.5);
  const plotH = height - axis - top;
  const y = (v: number) => top + plotH - (v / nice) * plotH;
  const ticks = [0, nice / 2, nice];
  const shown = data.find((d) => d.key === active);

  return (
    <figure className={styles.figure} aria-labelledby={`${id}-t`}>
      <figcaption id={`${id}-t`} className="visually-hidden">
        {title}
      </figcaption>
      <div className={styles.plot}>
        <svg viewBox={`0 0 ${width} ${height}`} className={styles.svg} role="group" aria-label={title}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={0} x2={width} y1={y(t)} y2={y(t)} className={styles.grid} />
              <text x={0} y={y(t) - 4} className={styles.tick}>
                {Number.isInteger(t) ? t : t.toFixed(1)}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const cx = band * i + band / 2;
            const h = Math.max(0, y(0) - y(d.value));
            const r = Math.min(4, h / 2);
            const x0 = cx - bar / 2;
            const yTop = y(d.value);
            const path =
              h === 0
                ? ""
                : `M${x0},${y(0)} L${x0},${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} L${x0 + bar - r},${yTop} Q${x0 + bar},${yTop} ${x0 + bar},${yTop + r} L${x0 + bar},${y(0)} Z`;
            return (
              <g
                key={d.key}
                tabIndex={0}
                role="img"
                aria-label={`${d.label}: ${d.value} ${unit}`}
                className={styles.hit}
                onPointerEnter={() => setActive(d.key)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(d.key)}
                onBlur={() => setActive(null)}
              >
                <rect x={band * i} y={top} width={band} height={plotH} fill="transparent" />
                {path && <path d={path} fill={d.color ?? "var(--seq-4)"} className={active === d.key ? styles.markActive : undefined} />}
                <text x={cx} y={yTop - 6} textAnchor="middle" className={styles.capLabel}>
                  {d.value}
                </text>
                <text x={cx} y={height - 8} textAnchor="middle" className={styles.axisLabel}>
                  {d.label}
                </text>
              </g>
            );
          })}
          <line x1={0} x2={width} y1={y(0)} y2={y(0)} className={styles.baseline} />
        </svg>
        <div className={styles.tooltip} aria-hidden="true" style={{ opacity: shown ? 1 : 0 }}>
          {shown && (
            <>
              <strong>
                {shown.value} {unit}
              </strong>
              <span>{shown.label}</span>
            </>
          )}
        </div>
      </div>
    </figure>
  );
}

/** Horizontal bars in a fixed order with values at the tip. One color unless color means state. */
export function BarList({ data, unit }: { data: Datum[]; unit: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className={styles.barList}>
      {data.map((d) => (
        <li key={d.key} className={styles.barRow} tabIndex={0} aria-label={`${d.label}: ${d.value} ${unit}`}>
          <span className={styles.barLabel}>{d.label}</span>
          <span className={styles.barTrack}>
            {d.value > 0 && (
              <span className={styles.bar} style={{ width: `${(d.value / max) * 100}%`, background: d.color ?? "var(--seq-4)" }} />
            )}
            <span className={styles.barValue}>{d.value}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Every chart has a table twin: the dependable way to read exact values. */
export function TableView({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <details className={styles.tableView}>
      <summary>Show as a table</summary>
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
