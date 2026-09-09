"use client";

import { useRef, useState } from "react";
import type { DealDoc } from "@/lib/api";

type VersionDoc = DealDoc & {
  version?: number;
  supersedes_id?: number | null;
  superseded_by_id?: number | null;
  original_state?: string;
  replacement_reason?: string | null;
};

export function DocumentVersions({ docs, refresh }: { docs: VersionDoc[]; refresh: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const requestKey = useRef<string | null>(null);

  async function mutate(doc: VersionDoc, action: "revision" | "issue") {
    setBusy(true);
    setError("");
    if (action === "revision") requestKey.current ??= crypto.randomUUID();
    try {
      const res = await fetch(`/api/sales/documents/${doc.id}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        ...(action === "revision" ? { body: JSON.stringify({ reason, request_key: requestKey.current }) } : {}),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Не удалось изменить документ");
      }
      setEditing(null);
      requestKey.current = null;
      setReason("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Ошибка запроса");
    } finally {
      setBusy(false);
    }
  }

  if (!docs.length) return null;
  return (
    <details className="mt-3 rounded-lg border border-line p-3">
      <summary className="cursor-pointer text-sm font-medium">История версий ({docs.length})</summary>
      <p className="my-2 text-xs text-muted">Новая версия создаётся как черновик. Оплата остаётся у прежнего документа.</p>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <ul className="space-y-3">
        {docs.map((doc) => (
          <li key={doc.id} className="border-t border-line pt-2 text-xs" aria-label={`Документ ${doc.id}`}>
            <div>{doc.kind === "invoice" ? "Счёт" : doc.kind === "contract" ? "Договор" : "Заказ"} · версия {doc.version ?? 1} · ID {doc.id} · {doc.amount.toFixed(2)} BYN</div>
            {doc.supersedes_id && <div>Заменяет документ #{doc.supersedes_id}</div>}
            {doc.superseded_by_id && <div>Заменён документом #{doc.superseded_by_id}; оплата: {doc.status === "paid" ? "оплачен" : "не подтверждена"}</div>}
            {doc.replacement_reason && <div>Причина: {doc.replacement_reason}</div>}
            {doc.original_state === "legacy_unavailable" && <p className="text-amber-700">Первоначальный оригинал не сохранён. Историческое содержание неизвестно.</p>}
            {(doc.original_state === "issued" || doc.original_state === "approval_copy") && (
              <a className="mr-3 text-accent-ink underline" href={`/api/sales/documents/${doc.id}/render`} target="_blank" rel="noreferrer">
                {doc.original_state === "issued" ? "Оригинал" : "На согласовании"} #{doc.id}
              </a>
            )}
            {doc.status === "draft" && <>
              <a className="mr-3 text-accent-ink underline" href={`/api/sales/documents/${doc.id}/preview`} target="_blank" rel="noreferrer">Предпросмотр черновика</a>
              <button className="underline" disabled={busy} onClick={() => void mutate(doc, "issue")}>
                {doc.kind === "contract" ? "Отправить версию на согласование" : "Выпустить версию"}
              </button>
            </>}
            {!doc.superseded_by_id && ["posted", "paid", "cancelled", "rejected"].includes(doc.status) && (
              <button className="underline" disabled={busy} onClick={() => { setEditing(doc.id); setReason(""); requestKey.current = null; }}>
                Новая версия #{doc.id}
              </button>
            )}
            {editing === doc.id && <div className="mt-2 flex flex-wrap gap-2">
              <input aria-label="Причина новой версии" className="rounded border border-line bg-surface p-2" value={reason}
                maxLength={500} onChange={(e) => { setReason(e.target.value); requestKey.current = null; }} />
              <button disabled={busy || reason.trim().length < 3} onClick={() => void mutate(doc, "revision")}>Создать черновик</button>
            </div>}
          </li>
        ))}
      </ul>
    </details>
  );
}
