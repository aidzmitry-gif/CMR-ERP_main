"use client";

import { useEffect, useState } from "react";

type Change = { before: unknown; after: unknown };
type HistoryRow = { id: number; actor: string; changed_at: string; deal_number: string;
  organization_id: number | null; event_type?: string; item_id?: number | null;
  sku_code?: string | null; item_action?: string | null; changes: Record<string, Change> };
type HistoryPage = { deal_id: number; items: HistoryRow[]; next_before_id: number | null };
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
function validPage(value: unknown, dealId: string): value is HistoryPage {
  if (!object(value) || value.deal_id !== Number(dealId) || !Array.isArray(value.items)
    || !(value.next_before_id === null || (Number.isSafeInteger(value.next_before_id) && Number(value.next_before_id) > 0))) return false;
  return value.items.every((row: unknown) => object(row) && Number.isSafeInteger(row.id) && Number(row.id) > 0
    && typeof row.actor === "string" && typeof row.changed_at === "string" && typeof row.deal_number === "string"
    && (row.organization_id === null || (Number.isSafeInteger(row.organization_id) && Number(row.organization_id) > 0))
    && (row.event_type === undefined || typeof row.event_type === "string")
    && (row.item_id === undefined || row.item_id === null || (Number.isSafeInteger(row.item_id) && Number(row.item_id) > 0))
    && (row.sku_code === undefined || row.sku_code === null || typeof row.sku_code === "string")
    && (row.item_action === undefined || row.item_action === null || typeof row.item_action === "string")
    && object(row.changes) && Object.values(row.changes).every((change) => object(change) && "before" in change && "after" in change));
}

const labels: Record<string, string> = {
  title: "Описание", amount: "Сумма", counterparty: "Контрагент", counterparty_id: "ID контрагента",
  stage: "Стадия", funnel: "Воронка", owner: "Ответственный", owner_id: "ID ответственного",
  next_step: "Следующий шаг", next_step_at: "Дата следующего шага", deal_date: "Дата сделки",
  ship_deadline: "Крайняя дата отгрузки", penalty_rate_pct: "Штраф за день",
  penalty_cap_pct: "Предел штрафа", penalty_terms: "Условия штрафа",
  sku_id: "ID товара", qty: "Количество", unit_price: "Цена за единицу",
};
const show = (value: unknown) => value == null || value === "" ? "не задано" : String(value);
const itemActions: Record<string, string> = { added: "добавлена", updated: "изменена", deleted: "удалена" };

export function DealFieldHistory({ dealId }: { dealId: string }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<HistoryRow[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [request, setRequest] = useState<{ before: number | null; revision: number } | null>(null);

  useEffect(() => {
    if (!request || !open) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: "20" });
    if (request.before !== null) params.set("before_id", String(request.before));
    fetch(`/api/sales/deals/${encodeURIComponent(dealId)}/field-history?${params}`, {
      cache: "no-store", signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("Не удалось загрузить историю изменений.");
      const data: unknown = await response.json();
      if (!validPage(data, dealId))
        throw new Error("Получена история другой сделки или некорректный ответ.");
      return data;
    }).then((data) => {
      if (controller.signal.aborted) return;
      setItems((previous) => request.before === null ? data.items : [...previous, ...data.items]);
      setNext(data.next_before_id);
    }).catch((reason: Error) => {
      if (!controller.signal.aborted) setError(reason.message);
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [dealId, open, request]);

  function load(before: number | null) {
    setLoading(true);
    setError("");
    setRequest({ before, revision: (request?.revision ?? 0) + 1 });
  }

  return <section aria-label="История изменений сделки" className="text-sm">
    <button className="text-accent-ink underline" aria-expanded={open} onClick={() => {
      if (!open) { setItems([]); setNext(null); load(null); }
      setOpen(!open);
    }}>История изменений</button>
    {open && <div className="mt-2 space-y-2 rounded border border-line p-3">
      <p className="text-muted">Ранние правки до включения журнала могут быть неизвестны.</p>
      {loading && <p role="status">Загрузка истории…</p>}
      {error && <p role="alert">{error} <button className="underline" onClick={() => load(request?.before ?? null)}>Повторить</button></p>}
      {!loading && !error && items.length === 0 && <p>Записанных изменений пока нет.</p>}
      {items.map((row) => <article key={row.id} className="border-t border-line pt-2">
        <p>Сделка {row.deal_number} · {row.changed_at} · {row.actor || "Автор неизвестен"}</p>
        {row.event_type === "sales.deal.item_changed" && <p>
          Позиция № {row.item_id ?? "?"}{row.sku_code ? ` · ${row.sku_code}` : ""}
          {row.item_action ? ` · ${itemActions[row.item_action] ?? row.item_action}` : ""}
        </p>}
        {row.organization_id === null && <p className="text-muted">Юрлицо на момент правки не установлено.</p>}
        {Object.entries(row.changes).map(([field, values]) => <p key={field}>
          {labels[field] || field}: было «{show(values.before)}», стало «{show(values.after)}».
        </p>)}
      </article>)}
      {next !== null && <button className="text-accent-ink underline" disabled={loading} onClick={() => load(next)}>Более ранние изменения</button>}
    </div>}
  </section>;
}
