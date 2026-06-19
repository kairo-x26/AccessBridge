"use client";

import { useState } from "react";

import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { inputClass } from "@/components/ui/Field";
import { Panel } from "@/components/ui/Panel";
import { useToast } from "@/components/ui/Toast";
import { api, type ReferralDetail, type Task } from "@/lib/api";
import { relative } from "@/lib/format";
import { useMe } from "@/lib/hooks";

import styles from "./referral.module.css";

export const PRIORITY_TONE = { urgent: "alert", high: "exception", normal: "neutral", low: "closed" } as const;

export function TaskItem({
  task,
  canManage,
  names,
  onChange,
}: {
  task: Task;
  canManage: boolean;
  names: Record<string, string>;
  onChange: () => void;
}) {
  const toast = useToast();
  const { data: me } = useMe();
  const [resolving, setResolving] = useState(false);
  const [note, setNote] = useState("");
  const [now] = useState(() => Date.now());
  const overdue = task.due_at && new Date(task.due_at).getTime() < now;

  async function patch(body: Record<string, unknown>, done: string) {
    try {
      await api.patch(`/tasks/${task.id}`, body);
      toast(done);
      setResolving(false);
      onChange();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Not saved.", "error");
    }
  }

  return (
    <li className={styles.task}>
      <div className={styles.taskHead}>
        <span className={styles.taskTitle}>{task.title}</span>
        {task.priority !== "normal" && <Tag tone={PRIORITY_TONE[task.priority as keyof typeof PRIORITY_TONE] ?? "neutral"}>{task.priority}</Tag>}
        {task.created_by.startsWith("agent") && <Tag tone="agent">From the agent</Tag>}
      </div>
      {task.detail && <p className={styles.taskDetail}>{task.detail}</p>}
      <p className={styles.taskMeta}>
        <span className={overdue ? styles.overdue : undefined}>
          {task.due_at ? `Due ${relative(task.due_at)}` : "No due date"}
        </span>
        <span>{task.owner_id ? (names[task.owner_id] ?? "Assigned") : "Unassigned"}</span>
      </p>
      {canManage &&
        (resolving ? (
          <div className={styles.inlineEdit}>
            <label>
              <span className="visually-hidden">What was done</span>
              <input className={inputClass} placeholder="What was done?" value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
            </label>
            <Button size="sm" variant="primary" disabled={note.trim().length < 2} onClick={() => patch({ status: "done", resolution: note }, "Task done.")}>
              Mark done
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setResolving(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className={styles.candidateActions}>
            <Button size="sm" onClick={() => setResolving(true)}>
              Mark done
            </Button>
            {me && task.owner_id !== me.id && (
              <Button size="sm" variant="quiet" onClick={() => patch({ owner_id: me.id }, "Assigned to you.")}>
                Take it
              </Button>
            )}
          </div>
        ))}
    </li>
  );
}

export function ReferralTasks({
  referral,
  canManage,
  names,
  onChange,
}: {
  referral: ReferralDetail;
  canManage: boolean;
  names: Record<string, string>;
  onChange: () => void;
}) {
  // Approvals are handled on the route and in agent activity, so they aren't repeated here.
  const open = referral.tasks.filter((t) => ["open", "in_progress"].includes(t.status) && t.kind !== "approval");
  const closed = referral.tasks.length - open.length;
  return (
    <Panel title="Tasks" description={closed ? `${closed} finished task${closed === 1 ? "" : "s"} not shown.` : undefined}>
      {open.length === 0 ? (
        <p className={styles.muted}>Nothing waiting on this referral.</p>
      ) : (
        <ul className={styles.tasks}>
          {open.map((t) => (
            <TaskItem key={t.id} task={t} canManage={canManage} names={names} onChange={onChange} />
          ))}
        </ul>
      )}
    </Panel>
  );
}
