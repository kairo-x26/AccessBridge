"use client";

import { Upload } from "lucide-react";
import { Fragment, useState, type FormEvent } from "react";

import { PageHeader } from "@/components/app/PageHeader";
import { Tag } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field, inputClass } from "@/components/ui/Field";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { EmptyState, Skeleton } from "@/components/ui/States";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type Schemas } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { can, useApi, useMe } from "@/lib/hooks";

import styles from "./policies.module.css";

type Policy = Schemas["PolicyOut"];
type PolicyDetail = Schemas["PolicyDetail"];
type Answer = Schemas["AnswerOut"];

/** Turn "[2]" markers into links to the matching citation card. */
function WithCitations({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className={styles.answerText}>
      {parts.map((p, i) => {
        const m = p.match(/^\[(\d+)\]$/);
        return m ? (
          <a key={i} href={`#source-${m[1]}`} className={styles.marker} aria-label={`Source ${m[1]}`}>
            {m[1]}
          </a>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        );
      })}
    </p>
  );
}

export function Policies() {
  const { data: me } = useMe();
  const toast = useToast();
  const { data: docs, mutate } = useApi<Policy[]>("/policies");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asking, setAsking] = useState(false);
  const [viewing, setViewing] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const { data: detail } = useApi<PolicyDetail>(viewing ? `/policies/${viewing}` : null);
  const manage = can(me, "policy:manage");

  async function ask(e: FormEvent) {
    e.preventDefault();
    setAsking(true);
    try {
      setAnswer(await api.post<Answer>("/policies/ask", { question }));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Couldn't search.", "error");
    } finally {
      setAsking(false);
    }
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const res = await fetch("/api/v1/policies", { method: "POST", body: form });
    const body = await res.json();
    if (!res.ok) {
      toast(body?.error?.message ?? "Upload failed.", "error");
      return;
    }
    toast("Uploaded as a draft. A second staff member must approve it before it's searchable.");
    setUploading(false);
    mutate();
  }

  async function act(id: string, action: "approve" | "archive") {
    try {
      await api.post(`/policies/${id}/${action}`);
      toast(action === "approve" ? "Approved. It's now searchable." : "Archived.");
      mutate();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Not saved.", "error");
    }
  }

  return (
    <>
      <PageHeader
        title="Policies"
        description="Ask about your clinic's approved referral procedures. Answers quote the procedure and link to it."
        actions={
          manage && (
            <Button icon={<Upload />} onClick={() => setUploading(true)}>
              Upload a procedure
            </Button>
          )
        }
      />
      <div className={styles.grid}>
        <div className={styles.main}>
          <form onSubmit={ask} className={styles.ask}>
            <Field label="Your question" hint="For example: how long before we follow up with a specialist office?">
              {(p) => <textarea {...p} className={inputClass} value={question} onChange={(e) => setQuestion(e.target.value)} rows={2} required minLength={3} />}
            </Field>
            <Button type="submit" variant="primary" busy={asking} disabled={question.trim().length < 3}>
              Search procedures
            </Button>
          </form>

          {answer && (
            <section aria-live="polite" className={styles.answer}>
              {answer.warnings.map((w) => (
                <Notice key={w} tone="warning">
                  {w}
                </Notice>
              ))}
              {answer.found ? (
                <>
                  <p className={styles.method}>
                    {answer.method === "model" ? "Written by the assistant from your procedures" : "Quoted from your procedures"}
                  </p>
                  <WithCitations text={answer.answer} />
                  <ol className={styles.sources}>
                    {answer.citations.map((c) => (
                      <li key={c.number} id={`source-${c.number}`} className={styles.source}>
                        <span className={styles.sourceNo}>{c.number}</span>
                        <div>
                          <button type="button" className={styles.sourceTitle} onClick={() => setViewing(c.document_id)}>
                            {c.title}
                          </button>
                          <span className={styles.muted}>
                            {c.heading ? `${c.heading}, ` : ""}version {c.version}
                          </span>
                          <blockquote className={styles.excerpt}>{c.excerpt}</blockquote>
                        </div>
                      </li>
                    ))}
                  </ol>
                </>
              ) : (
                <Notice tone="info" title="Not in your procedures">
                  {answer.answer}
                </Notice>
              )}
            </section>
          )}
        </div>

        <Panel title="Procedure library" description="Only approved versions are searched.">
          {!docs ? (
            <Skeleton lines={4} />
          ) : docs.length === 0 ? (
            <EmptyState title="No procedures yet">Upload your referral procedures to make them searchable.</EmptyState>
          ) : (
            <ul className={styles.library}>
              {docs.map((d) => (
                <li key={d.id}>
                  <button type="button" className={styles.sourceTitle} onClick={() => setViewing(d.id)}>
                    {d.title}
                  </button>
                  <div className={styles.docMeta}>
                    <Tag tone={d.status === "approved" ? "verified" : "neutral"}>
                      {d.status === "approved" ? `Approved, v${d.version}` : `Draft, v${d.version}`}
                    </Tag>
                    {d.flagged_passages > 0 && <Tag tone="exception">{d.flagged_passages} passage needs review</Tag>}
                    <span className={styles.muted}>{formatDate(d.approved_at ?? d.created_at)}</span>
                  </div>
                  {manage && (
                    <div className={styles.docActions}>
                      {d.status === "draft" && d.uploaded_by !== `user:${me?.id}` && (
                        <Button size="sm" onClick={() => act(d.id, "approve")}>
                          Approve
                        </Button>
                      )}
                      {d.status === "draft" && d.uploaded_by === `user:${me?.id}` && (
                        <span className={styles.muted}>Waiting for another reviewer</span>
                      )}
                      <Button size="sm" variant="quiet" onClick={() => act(d.id, "archive")}>
                        Archive
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Dialog open={!!viewing} onClose={() => setViewing(null)} title={detail?.title ?? "Procedure"}>
        {!detail ? <Skeleton lines={6} /> : <pre className={styles.content}>{detail.content}</pre>}
      </Dialog>

      <Dialog open={uploading} onClose={() => setUploading(false)} title="Upload a procedure">
        <form onSubmit={upload} style={{ display: "grid", gap: 14 }}>
          <Field label="Title" hint="Uploading with an existing title creates a new version.">
            {(p) => <input {...p} name="title" className={inputClass} required maxLength={200} />}
          </Field>
          <Field label="File" hint="Text, Markdown or a text-based PDF, under 2 MB.">
            {(p) => <input {...p} name="file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" className={inputClass} required />}
          </Field>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
            <Button onClick={() => setUploading(false)}>Cancel</Button>
            <Button type="submit" variant="primary">
              Upload draft
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
