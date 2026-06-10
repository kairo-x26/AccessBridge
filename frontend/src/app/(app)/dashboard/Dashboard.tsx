"use client";

import { Download } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/app/PageHeader";
import { BarList, ColumnChart, HeroFigure, Meter, StatTile, TableView } from "@/components/charts/Charts";
import { inputClass } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { ErrorState, Skeleton } from "@/components/ui/States";
import { ROUTE, SPECIALTY_LABEL, STATUS_LABEL, label } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import styles from "./dashboard.module.css";

type Report = {
  generated_at: string;
  totals: {
    referrals: number;
    open: number;
    exceptions: number;
    completed: number;
    completed_care_rate: number | null;
    visibility: number | null;
    unassigned_open: number;
    open_tasks: number;
    overdue_tasks: number;
    median_days_to_submitted: number | null;
    median_days_to_completed: number | null;
  };
  status_distribution: Record<string, number>;
  age_buckets: { label: string; count: number }[];
  by_specialty: { specialty: string; total: number; open: number; completed: number; exceptions: number; completion_rate: number }[];
  by_owner: { owner_id: string | null; owner_name: string; open_referrals?: number; open_tasks?: number; overdue_tasks?: number }[];
  agent: { proposals: number; by_decision: Record<string, number>; approved: number; rejected: number; acceptance_rate: number | null };
  definitions: Record<string, string>;
};

const RANGES = { "": "All time", "30": "Imported in the last 30 days", "90": "Imported in the last 90 days" } as const;
const pct = (v: number | null) => (v == null ? "—" : `${Math.round(v * 100)}%`);
const days = (v: number | null) => (v == null ? "—" : `${v} days`);
const SEQ = ["var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];

export function Dashboard() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me } = useMe();
  const range = params.get("range") ?? "";
  const specialty = params.get("specialty") ?? "";

  const q = new URLSearchParams();
  if (specialty) q.set("specialty", specialty);
  if (range) q.set("since", new Date(Date.now() - Number(range) * 86_400_000).toISOString());
  const { data: r, error, mutate, isValidating } = useApi<Report>(`/reports/referrals?${q}`, { keepPreviousData: true });

  function set(key: string, v: string) {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(key, v);
    else next.delete(key);
    router.replace(`${pathname}?${next}`, { scroll: false });
  }

  if (error) return <ErrorState error={error} retry={() => mutate()} />;

  const statusData = [
    ...ROUTE.slice(1).map((s) => ({ key: s.status, label: STATUS_LABEL[s.status], value: r?.status_distribution[s.status] ?? 0 })),
    { key: "exception", label: STATUS_LABEL.exception, value: r?.status_distribution.exception ?? 0, color: "var(--exception)" },
    {
      key: "closed",
      label: "Declined or cancelled",
      value: (r?.status_distribution.declined ?? 0) + (r?.status_distribution.cancelled ?? 0),
      color: "var(--mark-muted)",
    },
  ];

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="How referrals are moving, where they're stuck, and who owns them."
        actions={
          can(me, "report:export") && (
            <a className={styles.export} href={`/api/v1/reports/referrals.csv?${q}`}>
              <Download aria-hidden="true" size={18} /> Download CSV
            </a>
          )
        }
      />
      <div className={styles.filters}>
        <label>
          <span className="visually-hidden">Time range</span>
          <select className={inputClass} value={range} onChange={(e) => set("range", e.target.value)}>
            {Object.entries(RANGES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="visually-hidden">Specialty</span>
          <select className={inputClass} value={specialty} onChange={(e) => set("specialty", e.target.value)}>
            <option value="">All specialties</option>
            {Object.entries(SPECIALTY_LABEL)
              .filter(([k]) => !["unsupported", "unspecified"].includes(k))
              .map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
          </select>
        </label>
      </div>

      {!r ? (
        <Skeleton lines={10} label="Loading metrics" />
      ) : (
        <div className={styles.body} style={{ opacity: isValidating ? 0.6 : 1 }}>
          <section className={styles.headline} aria-label="Headline">
            <HeroFigure
              label="Referrals with verified completed care"
              value={pct(r.totals.completed_care_rate)}
              detail={`${r.totals.completed} of ${r.totals.referrals} referrals. Counts only a consult note or specialist confirmation, never a scheduled visit or a delivered text.`}
            />
            <div className={styles.tiles}>
              <StatTile label="Open referrals" value={String(r.totals.open)} note={`${r.totals.unassigned_open} without an owner`} />
              <StatTile label="Exceptions" value={String(r.totals.exceptions)} tone={r.totals.exceptions ? "warning" : undefined} note="Need a person" />
              <StatTile label="Overdue tasks" value={String(r.totals.overdue_tasks)} tone={r.totals.overdue_tasks ? "warning" : undefined} note={`of ${r.totals.open_tasks} open`} />
              <StatTile label="Visibility" value={pct(r.totals.visibility)} note="Open, owned and updated in 30 days" />
              <StatTile label="Time to send" value={days(r.totals.median_days_to_submitted)} note="Median, import to sent" />
              <StatTile label="Time to completed care" value={days(r.totals.median_days_to_completed)} note="Median, import to completed" />
            </div>
          </section>

          <div className={styles.grid}>
            <Panel title="How long open referrals have waited" description="Darker columns have waited longer.">
              <ColumnChart
                title="Open referrals by days since import"
                unit="open referrals"
                data={r.age_buckets.map((b, i) => ({ key: b.label, label: b.label, value: b.count, color: SEQ[i] }))}
              />
              <TableView columns={["Waiting", "Open referrals"]} rows={r.age_buckets.map((b) => [b.label, b.count])} />
            </Panel>

            <Panel title="Where referrals are now" description="In route order. Exceptions are operational, not clinical.">
              <BarList data={statusData} unit="referrals" />
              <TableView columns={["Status", "Referrals"]} rows={statusData.map((d) => [d.label, d.value])} />
            </Panel>

            <Panel title="By specialty">
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Specialty</th>
                    <th scope="col" className={styles.num}>Open</th>
                    <th scope="col" className={styles.num}>Exceptions</th>
                    <th scope="col">Completed care</th>
                  </tr>
                </thead>
                <tbody>
                  {r.by_specialty.map((s) => (
                    <tr key={s.specialty}>
                      <th scope="row">{label(SPECIALTY_LABEL, s.specialty)}</th>
                      <td className={styles.num}>{s.open}</td>
                      <td className={styles.num}>{s.exceptions || "—"}</td>
                      <td>
                        <Meter value={s.completion_rate} label={`${label(SPECIALTY_LABEL, s.specialty)} completed care`} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel title="By owner">
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Owner</th>
                    <th scope="col" className={styles.num}>Open referrals</th>
                    <th scope="col" className={styles.num}>Open tasks</th>
                    <th scope="col" className={styles.num}>Overdue</th>
                  </tr>
                </thead>
                <tbody>
                  {r.by_owner.map((o) => (
                    <tr key={o.owner_id ?? "none"}>
                      <th scope="row" className={o.owner_id ? undefined : styles.unassigned}>{o.owner_name}</th>
                      <td className={styles.num}>{o.open_referrals ?? 0}</td>
                      <td className={styles.num}>{o.open_tasks ?? 0}</td>
                      <td className={`${styles.num} ${o.overdue_tasks ? styles.overdue : ""}`}>{o.overdue_tasks ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel title="Agent proposals" description="How often staff agree with what the agent proposes.">
              <div className={styles.tilesSmall}>
                <StatTile label="Proposals" value={String(r.agent.proposals)} />
                <StatTile label="Done automatically" value={String(r.agent.by_decision.auto ?? 0)} note="Internal steps only" />
                <StatTile label="Sent for approval" value={String(r.agent.by_decision.approval_required ?? 0)} />
                <StatTile label="Blocked by policy" value={String(r.agent.by_decision.denied ?? 0)} />
                <StatTile label="Staff approved" value={pct(r.agent.acceptance_rate)} note={`${r.agent.approved} approved, ${r.agent.rejected} rejected`} />
              </div>
            </Panel>

            <Panel title="How these numbers are defined">
              <dl className={styles.defs}>
                {Object.entries(r.definitions).map(([k, v]) => (
                  <div key={k}>
                    <dt>{k.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase())}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>
          <p className={styles.generated}>
            Updated {new Date(r.generated_at).toLocaleString("en-US")}. All figures are aggregate counts; no patient
            details are included.
          </p>
        </div>
      )}
    </>
  );
}

