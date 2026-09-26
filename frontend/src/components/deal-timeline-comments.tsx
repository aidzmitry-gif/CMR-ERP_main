"use client";

import { useEffect, useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";

type TimelineComment = {
  id: number | string;
  body: string;
  author_display: string | null;
  created_at: string;
};

type LoadState =
  | { status: "loading" }
  | { status: "ok"; rows: TimelineComment[] }
  | { status: "unauthorized" | "forbidden" | "error" };

type TimelineAttachment = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
};

type AttachmentState =
  | { status: "loading" }
  | { status: "ok"; rows: TimelineAttachment[] }
  | { status: "unauthorized" | "forbidden" | "error" };

function positiveId(value: number | string): number | null {
  const number = typeof value === "number" ? value : Number(value);
  return /^\d+$/.test(String(value)) && Number.isSafeInteger(number) && number > 0 ? number : null;
}

function validAttachment(value: unknown): value is TimelineAttachment {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return typeof row.id === "number" && positiveId(row.id) !== null
    && typeof row.filename === "string" && row.filename.trim().length > 0
    && typeof row.content_type === "string"
    && typeof row.size_bytes === "number" && Number.isSafeInteger(row.size_bytes) && row.size_bytes >= 0;
}

function formatSize(bytes: number): string {
  return `${new Intl.NumberFormat("ru-RU").format(bytes)} байт`;
}

function CommentAttachments({ dealId, commentId }: { dealId: number; commentId: number }) {
  const [state, setState] = useState<AttachmentState>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  const base = `/api/sales/deals/${dealId}/timeline/comments/${commentId}/attachments`;

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void (async () => {
      try {
        const response = await fetch(base, { cache: "no-store", signal: controller.signal });
        if (!live) return;
        if (response.status === 401) { setState({ status: "unauthorized" }); return; }
        if (response.status === 403 || response.status === 404) { setState({ status: "forbidden" }); return; }
        if (!response.ok) { setState({ status: "error" }); return; }
        const rows: unknown = await response.json();
        if (!live) return;
        setState(Array.isArray(rows) && rows.every(validAttachment)
          ? { status: "ok", rows }
          : { status: "error" });
      } catch {
        if (live) setState({ status: "error" });
      }
    })();
    return () => { live = false; controller.abort(); };
  }, [base, revision]);

  return <div className="mt-2 text-xs text-muted">
    {state.status === "loading" && <p role="status">Загрузка вложений…</p>}
    {state.status === "unauthorized" && <p role="alert">Сессия истекла. Войдите снова, чтобы увидеть вложения.</p>}
    {state.status === "forbidden" && <p role="alert">Вложения этого комментария недоступны.</p>}
    {state.status === "error" && <p role="alert">Не удалось загрузить вложения. <button type="button" className="underline" onClick={() => {
      setState({ status: "loading" });
      setRevision((value) => value + 1);
    }}>Повторить загрузку вложений</button></p>}
    {state.status === "ok" && state.rows.length === 0 && <p>Вложений нет.</p>}
    {state.status === "ok" && state.rows.length > 0 && <ul className="space-y-1">
      {state.rows.map((attachment) => <li key={attachment.id}>
        <a className="underline" download href={`${base}/${attachment.id}/download`}>{attachment.filename}</a>
        <span> · {formatSize(attachment.size_bytes)}</span>
      </li>)}
    </ul>}
  </div>;
}

function TimelineCommentRow({ dealId, comment }: { dealId: string; comment: TimelineComment }) {
  const [expanded, setExpanded] = useState(false);
  const numericDealId = positiveId(dealId);
  const numericCommentId = positiveId(comment.id);
  return <li className="rounded-lg bg-sunken px-3 py-2.5">
    <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted">
      <span className="font-medium text-ink">{comment.author_display || "Автор не указан"}</span>
      <time dateTime={comment.created_at}>{displayTime(comment.created_at)}</time>
    </div>
    <p className="mt-1 whitespace-pre-wrap break-words text-sm text-ink">{comment.body}</p>
    {numericDealId !== null && numericCommentId !== null && <>
      <button type="button" className="mt-2 text-xs underline" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>
        Вложения
      </button>
      {expanded && <CommentAttachments dealId={numericDealId} commentId={numericCommentId} />}
    </>}
  </li>;
}

function validComment(value: unknown): value is TimelineComment {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  return (typeof row.id === "number" && Number.isSafeInteger(row.id) && row.id > 0
      || typeof row.id === "string" && row.id.length > 0)
    && typeof row.body === "string"
    && (typeof row.author_display === "string" || row.author_display === null)
    && typeof row.created_at === "string" && row.created_at.length > 0;
}

function displayTime(value: string): string {
  const parsed = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ru-RU", {
    timeZone: "Europe/Minsk",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function DealTimelineComments({ dealId }: { dealId: string }) {
  return <DealTimelineCommentsBody key={dealId} dealId={dealId} />;
}

function DealTimelineCommentsBody({ dealId }: { dealId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    void (async () => {
      try {
        const response = await fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/timeline/comments`, {
          cache: "no-store", signal: controller.signal,
        });
        if (!live) return;
        if (response.status === 401) { setState({ status: "unauthorized" }); return; }
        if (response.status === 403 || response.status === 404) { setState({ status: "forbidden" }); return; }
        if (!response.ok) { setState({ status: "error" }); return; }
        const rows: unknown = await response.json();
        if (!live) return;
        setState(Array.isArray(rows) && rows.every(validComment)
          ? { status: "ok", rows }
          : { status: "error" });
      } catch {
        if (live) setState({ status: "error" });
      }
    })();
    return () => { live = false; controller.abort(); };
  }, [dealId, revision]);

  function retry() {
    setState({ status: "loading" });
    setRevision((value) => value + 1);
  }

  return <Card>
    <CardHeader>Комментарии из истории сделки</CardHeader>
    <CardBody className="space-y-2.5">
      {state.status === "loading" && <p role="status" className="text-sm text-muted">Загрузка комментариев…</p>}
      {state.status === "unauthorized" && <p role="alert" className="text-sm text-muted">Сессия истекла. Войдите снова, чтобы увидеть комментарии.</p>}
      {state.status === "forbidden" && <p role="alert" className="text-sm text-muted">Комментарии этой сделки недоступны.</p>}
      {state.status === "error" && <div role="alert" className="text-sm text-muted">
        Не удалось загрузить комментарии. <button type="button" onClick={retry} className="underline">Повторить</button>
      </div>}
      {state.status === "ok" && state.rows.length === 0 &&
        <p className="text-sm text-muted">Комментариев в истории сделки нет.</p>}
      {state.status === "ok" && state.rows.length > 0 && <ol className="space-y-2">
        {state.rows.map((comment) => <TimelineCommentRow key={comment.id} dealId={dealId} comment={comment} />)}
      </ol>}
    </CardBody>
  </Card>;
}
