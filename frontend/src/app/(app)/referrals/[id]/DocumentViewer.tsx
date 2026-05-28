"use client";

import { useEffect, useRef } from "react";

import { Dialog } from "@/components/ui/Dialog";
import { Notice } from "@/components/ui/Notice";
import { Skeleton } from "@/components/ui/States";
import { useApi } from "@/lib/hooks";

import styles from "./referral.module.css";

type DocText = { id: string; text: string | null; extraction_status: string };

/** Shows a document's text with the cited span highlighted: the evidence behind a value. */
export function DocumentViewer({
  documentId,
  title,
  highlight,
  onClose,
}: {
  documentId: string | null;
  title: string;
  highlight?: [number, number];
  onClose: () => void;
}) {
  const { data, error } = useApi<DocText>(documentId ? `/documents/${documentId}/text` : null, {
    revalidateOnFocus: false,
  });
  const markRef = useRef<HTMLElement>(null);
  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center" });
  }, [data, highlight]);

  const text = data?.text;
  return (
    <Dialog open={!!documentId} onClose={onClose} title={title}>
      {error && <Notice tone="error">{error.message}</Notice>}
      {!data && !error && <Skeleton lines={6} />}
      {data && !text && (
        <Notice tone="warning" title="No readable text">
          This file hasn&rsquo;t been read yet or is a scanned image.{" "}
          <a href={`/api/v1/documents/${documentId}/content`} target="_blank" rel="noreferrer">
            Open the original
          </a>
          .
        </Notice>
      )}
      {text && (
        <>
          <pre className={styles.docText}>
            {highlight ? (
              <>
                {text.slice(0, highlight[0])}
                <mark ref={markRef}>{text.slice(highlight[0], highlight[1])}</mark>
                {text.slice(highlight[1])}
              </>
            ) : (
              text
            )}
          </pre>
          <p className={styles.muted}>
            Opening a document is recorded in the audit log.{" "}
            <a href={`/api/v1/documents/${documentId}/content`} target="_blank" rel="noreferrer">
              Open the original file
            </a>
          </p>
        </>
      )}
    </Dialog>
  );
}
