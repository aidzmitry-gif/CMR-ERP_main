"use client";

import { useRef, useState } from "react";
import type { DealDoc } from "@/lib/api";
import { useUnsavedDocumentGuard } from "@/lib/use-unsaved-document-guard";

type Change = { before: string | null; after: string | null };
type HistoryRow = { id: number; actor: string; changed_at: string; changes: Record<string, Change> };

export function DealDocumentCard({ doc, refresh, label }: { doc: DealDoc; refresh: () => Promise<void>; label?: string }) {
  const [open, setOpen] = useState(false);
  const [payment, setPayment] = useState(doc.payment_terms ?? "");
  const [delivery, setDelivery] = useState(doc.delivery_terms ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const submitting = useRef(false);
  const changed = payment !== (doc.payment_terms ?? "") || delivery !== (doc.delivery_terms ?? "");
  const confirmClose = useUnsavedDocumentGuard(open && changed);

  async function loadHistory(beforeId?: number) {
    try {
      const url = `/api/sales/documents/${doc.id}/field-history?limit=20${beforeId ? `&before_id=${beforeId}` : ""}`;
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error("История документа недоступна.");
      const body = await response.json();
      if (body.document_id !== doc.id || !Array.isArray(body.items)) throw new Error("История документа не подтверждена.");
      setHistory((current) => beforeId ? [...current, ...body.items] : body.items);
      setNextBeforeId(typeof body.next_before_id === "number" ? body.next_before_id : null);
      setHistoryLoaded(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось открыть историю документа.");
      setHistoryLoaded(true);
    }
  }

  function reveal() {
    setPayment(doc.payment_terms ?? "");
    setDelivery(doc.delivery_terms ?? "");
    setError("");
    setHistoryLoaded(false);
    setHistory([]);
    setNextBeforeId(null);
    setOpen(true);
    void loadHistory();
  }

  function close() {
    if (!submitting.current && confirmClose()) setOpen(false);
  }

  async function save() {
    if (submitting.current) return;
    if (!doc.draft_edit_token || !/^[0-9a-f]{64}$/.test(doc.draft_edit_token)) {
      setError("Актуальная версия черновика не получена. Обновите реестр документов.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    const wanted = { payment_terms: payment.trim() || null, delivery_terms: delivery.trim() || null };
    try {
      const response = await fetch(`/api/sales/documents/${doc.id}/draft`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...wanted, expected_edit_token: doc.draft_edit_token }),
      });
      if (response.status === 409) {
        setError("Черновик изменился или уже выпущен. Ваши правки сохранены в форме; сверьте документ перед повтором.");
        return;
      }
      if (!response.ok) {
        setError("Сервер не подтвердил сохранение черновика. Правки оставлены в форме.");
        return;
      }
      const result = await response.json();
      if (result.id !== doc.id || result.status !== "draft" || result.payment_terms !== wanted.payment_terms ||
          result.delivery_terms !== wanted.delivery_terms || typeof result.draft_edit_token !== "string") {
        setError("Результат сохранения не подтверждён. Проверьте документ перед повтором.");
        return;
      }
      setOpen(false);
      await refresh();
    } catch {
      setError("Результат сохранения неизвестен. Проверьте документ перед повтором.");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const labels: Record<string, string> = { payment_terms: "Условия оплаты", delivery_terms: "Условия поставки" };
  return <div className="mt-1">
    <button type="button" className="text-accent-ink underline" aria-label={`Открыть документ № ${doc.number}`} onClick={open ? close : reveal}>
      {label ?? `Открыть документ № ${doc.number}`}
    </button>
    {open && <section className="mt-2 space-y-2 rounded border border-line bg-surface p-3" aria-label={`Карточка документа ${doc.number}`}>
      <div className="flex items-center justify-between gap-2"><strong>{doc.number} · версия {doc.version ?? 1} · {doc.status}</strong><button type="button" onClick={close} disabled={busy}>Закрыть</button></div>
      <p>Сделка: документ ID {doc.id}; сумма {doc.amount.toFixed(2)} в валюте оригинала.</p>
      {doc.status === "draft" ? <>
        <label className="block">Условия оплаты<input className="mt-1 w-full rounded border border-line bg-surface p-2" value={payment} maxLength={255} onChange={(event) => setPayment(event.target.value)} /></label>
        <label className="block">Условия поставки<input className="mt-1 w-full rounded border border-line bg-surface p-2" value={delivery} maxLength={255} onChange={(event) => setDelivery(event.target.value)} /></label>
        <button type="button" className="rounded bg-accent px-3 py-2 text-white disabled:opacity-50" disabled={busy} onClick={() => void save()}>{busy ? "Сохранение…" : "Сохранить и закрыть"}</button>
      </> : <><p>Условия оплаты: {doc.payment_terms || "Не указаны"}</p><p>Условия поставки: {doc.delivery_terms || "Не указаны"}</p></>}
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <h4 className="font-semibold">История изменений черновика</h4>
      {!historyLoaded && <p>Загрузка истории…</p>}
      {historyLoaded && history.length === 0 && !error && <p>Зафиксированных изменений нет; более ранние правки могут быть неизвестны.</p>}
      {history.map((row) => <div key={row.id} className="border-t border-line pt-2">
        <p>{row.actor} · {row.changed_at}</p>
        {Object.entries(row.changes).map(([field, value]) => <p key={field}>{labels[field] ?? field}: {value.before ?? "Не указано"} → {value.after ?? "Не указано"}</p>)}
      </div>)}
      {nextBeforeId && <button type="button" className="underline" onClick={() => void loadHistory(nextBeforeId)}>Показать более ранние изменения</button>}
    </section>}
  </div>;
}
