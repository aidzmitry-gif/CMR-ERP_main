"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingReceiptWarehouse } from "./accounting-receipt-warehouse";
import { AccountingReceiptPreview } from "./accounting-receipt-preview";

type Receipt = {
  id: number; organization_id: number; source: string; version: number; status: string;
  actor: string; created_at: string;
  document: {
    invoice_reference: string; currency: string; document_date: string; operation_date: string;
    supplier: string; contract: string; warehouse: string; explanation: string;
    items: { unit?: string | null; sku: string; lot: string; quantity: string; net_amount: string; vat_rate: string; vat_amount: string; vat_basis: string }[];
  };
};

export function AccountingReceiptSource({ org, receiptId, onPosted }: { org: string; receiptId: string; onPosted?: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<Receipt | null>(null);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function load() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setOpen(true); setBusy(true); setError(""); setData(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/receipts/${receiptId}/source`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(response.status === 409 ? "Не удалось подтвердить версию поступления. Обратитесь к главному бухгалтеру." : "Поступление недоступно. Проверьте права и наличие документа.");
      const result: Receipt = await response.json();
      if (String(result.organization_id) !== org || String(result.id) !== receiptId || result.source !== `procurement:receipt:${receiptId}` || !Number.isInteger(result.version) || result.version < 1 || !Array.isArray(result.document?.items)) throw new Error("Получен документ другой операции или неполные данные.");
      if (!controller.signal.aborted) setData(result);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить поступление.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="my-2 min-w-0">
    <Button variant="ghost" onClick={() => { if (open) { pending.current?.abort(); setOpen(false); setBusy(false); setData(null); } else void load(); }}>{open ? "Скрыть поступление" : "Открыть поступление"}</Button>
    {open && <section aria-label="Первичный документ поступления" className="space-y-3 rounded-lg border border-line p-3 text-sm">
      {busy && <p role="status">Загружается поступление…</p>}
      {error && <div><p role="alert">{error}</p><Button variant="ghost" onClick={() => void load()}>Повторить загрузку</Button></div>}
      {data && <>
        <p className="font-semibold">{data.document.invoice_reference} · Версия {data.version} · {data.status === "posted" ? "Проведённая версия" : "Черновик, не проведён"}</p>
        <p className="text-muted">Просмотр первичного документа. Управление поступлениями — в разделе «Закупки».</p>
        <dl className="grid gap-2 sm:grid-cols-2">
          {[["Дата документа", data.document.document_date], ["Дата операции", data.document.operation_date], ["Поставщик", data.document.supplier], ["Договор", data.document.contract], ["Склад", data.document.warehouse], ["Валюта", data.document.currency], ["Автор версии", data.actor], ["Зарегистрирована", data.created_at]].map(([label, value]) => <div key={label}><dt className="text-muted">{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <p>{data.document.explanation}</p>
        <div className="max-w-full overflow-x-auto"><table className="w-full text-left"><caption className="text-left font-semibold">Товары и суммы первичного документа, {data.document.currency}</caption><thead><tr>{["Номенклатура", "Партия", "Количество", "Единица", "Без НДС", "Ставка НДС, %", "НДС", "Основание НДС"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{data.document.items.map((item, index) => <tr key={index} className="border-t border-line">{[item.sku, item.lot, item.quantity, item.unit ?? "Не указана", item.net_amount, item.vat_rate, item.vat_amount, item.vat_basis].map((value, column) => <td key={column} className="p-2">{value}</td>)}</tr>)}</tbody></table></div>
        <AccountingReceiptWarehouse key={`${org}:${data.id}:${data.version}`} org={org} receiptId={data.id} version={data.version} />
        {data.status === "draft" && <AccountingReceiptPreview key={`${org}:${data.id}:${data.version}`} org={org} source={data} onVerified={() => { void load(); onPosted?.(); }} />}
      </>}
    </section>}
  </div>;
}
