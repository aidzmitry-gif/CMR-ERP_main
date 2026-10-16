"use client";

import { useState } from "react";

import { fetchPurchaseChain, type PurchaseChain } from "@/lib/procurement-machine";

const stageLabels = {
  request: "Заявка",
  order: "Заказ поставщику",
  incoming_invoice: "Накладная поступления",
  warehouse: "Складская приёмка",
} as const;

const stageValue = (value: string) => ({
  linked: "связана",
  owned: "подтверждён",
  posted: "проведена",
  draft: "черновик",
  accepted: "принята",
  pending: "ожидает",
  missing: "не зарегистрирована",
}[value] ?? value);

const blockerLabel = (value: string) => ({
  purchase_request_not_linked: "заявка не связана с заказом",
  incoming_invoice_not_registered: "накладная поступления не зарегистрирована",
  incoming_invoice_not_posted: "накладная поступления не проведена в бухгалтерии",
  warehouse_receipt_not_accepted: "складская приёмка не подтверждена",
}[value] ?? value);

export function ProcurementPurchaseChain({ org, orderId }: { org: number; orderId: number }) {
  const [chain, setChain] = useState<PurchaseChain | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setBusy(true); setError("");
    try { setChain(await fetchPurchaseChain(org, orderId)); }
    catch (e) { setError(e instanceof Error ? e.message : "Не удалось прочитать цепочку закупки"); }
    finally { setBusy(false); }
  }

  return <section className="space-y-2 rounded border border-line p-4" aria-label="Цепочка закупки">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="font-semibold">Цепочка закупки</h2><p className="text-sm text-muted">Заявка → заказ → накладная → бухгалтерия → склад.</p></div>
      <button disabled={busy} onClick={() => void load()}>{busy ? "Проверяем…" : chain ? "Обновить цепочку" : "Проверить цепочку"}</button>
    </div>
    {error && <p role="alert">{error}</p>}
    {chain && <>
      <div className="grid gap-2 sm:grid-cols-4">
        {(Object.keys(stageLabels) as (keyof typeof stageLabels)[]).map(key => <div className="rounded border border-line p-2" key={key}>
          <div className="text-xs text-muted">{stageLabels[key]}</div><div className="font-medium">{stageValue(chain.stages[key])}</div>
        </div>)}
      </div>
      {chain.status === "complete" ? <p role="status">Цепочка подтверждена по сохранённым источникам.</p> : <div role="status"><p>Цепочка неполная. Реестр не считает отсутствующие документы выполненными.</p><ul className="list-disc pl-5">{chain.blockers.map(item => <li key={item}>{blockerLabel(item)}</li>)}</ul></div>}
      {!!chain.request_links.length && <div><h3 className="font-medium">Связанные заявки</h3>{chain.request_links.map(item => <p key={item.id} className="text-sm">{item.number} · {item.item} · {item.quantity} шт. · {stageValue(item.stage)}</p>)}</div>}
      {!!chain.receipts.length && <div><h3 className="font-medium">Накладные поступления</h3>{chain.receipts.map(item => <article key={item.id} className="rounded border border-line p-2 text-sm"><p>{item.invoice_reference || `Документ №${item.id}`} · версия {item.version} · {stageValue(item.status)}</p><p>{item.posting ? `Проводка №${item.posting.entry_id}` : "Проводка отсутствует"} · {item.physical_acceptance.length ? `складская приёмка: ${item.physical_acceptance.map(x => x.receipt_id).join(", ")}` : "складская приёмка отсутствует"}</p></article>)}</div>}
      <p className="text-xs text-muted">Реестр показывает только внутренние подтверждённые источники; внешний документ ТН/ТТН здесь не выпускается.</p>
    </>}
  </section>;
}
