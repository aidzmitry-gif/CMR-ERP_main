"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Row = { position: number; sku: string; lot: string; unit: string | null; quantity: string; prepared: string; accepted: string; rejected: string; pending_qc: string; unallocated: string };
type Report = { organization_id: number; receipt_id: number; source_version: number; status: string; rows: Row[]; receipts: { receipt_id: number; number: string; source_version: number; warehouse: string; status: string }[] };

export function AccountingReceiptWarehouse({ org, receiptId, version }: { org: string; receiptId: number; version: number }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  async function load() {
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setBusy(true); setError(""); setReport(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/receipts/${receiptId}/warehouse-reconciliation`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("Не удалось сверить накладную со складом. Проверьте доступ и сохранённые связи.");
      const result: Report = await response.json();
      if (String(result.organization_id) !== org || result.receipt_id !== receiptId || result.source_version !== version || !Array.isArray(result.rows) || !Array.isArray(result.receipts) || !["linked", "unlinked", "version_conflict"].includes(result.status)) throw new Error("Версия или юрлицо сверки изменились. Откройте накладную заново.");
      if (!controller.signal.aborted) setReport(result);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить сверку."); }
    finally { if (!controller.signal.aborted) setBusy(false); }
  }
  return <section aria-label="Сверка накладной со складом" className="space-y-3 rounded-lg border border-line p-3">
    <Button variant="secondary" disabled={busy} onClick={() => void load()}>{busy ? "Сверяется со складом…" : "Сверить со складом"}</Button>
    {error && <p role="alert">{error}</p>}
    {report && <>
      {report.status === "version_conflict" ? <p role="alert">Накладная изменена после подготовки складской приёмки. Требуется сверка версий; общие количества не объединены.</p> : <>
        {report.status === "unlinked" && <p>Связанных складских приёмок нет. Это не подтверждает отсутствие товара на складе.</p>}
        <div className="max-w-full overflow-x-auto"><table className="w-full text-left"><caption>Количество по строкам накладной</caption>
          <thead><tr>{["Строка", "Товар", "Партия", "Единица", "По накладной", "Подготовлено", "Принято", "Брак", "Ожидает QC", "Не распределено"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead>
          <tbody>{report.rows.map(row => <tr key={row.position} className="border-t border-line">{[row.position, row.sku, row.lot, row.unit ?? "Не указана", row.quantity, row.prepared, row.accepted, row.rejected, row.pending_qc, row.unallocated].map((value, i) => <td key={i} className="p-2">{value}</td>)}</tr>)}</tbody>
        </table></div>
      </>}
      <ul>{report.receipts.map(receipt => <li key={receipt.receipt_id}>{receipt.number} · версия накладной {receipt.source_version} · {receipt.warehouse} · {receipt.status === "accepted" ? "Принята" : "Ожидает QC"}</li>)}</ul>
      <p className="text-muted">Подготовленная приёмка не является складским остатком. Эта сверка количеств не подтверждает окончательную себестоимость.</p>
    </>}
  </section>;
}
