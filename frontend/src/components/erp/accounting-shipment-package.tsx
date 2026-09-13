"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { AccountingSourceLink } from "./accounting-source-link";

type SavedPackage = {
  organization_id: number; source: string; actor: string; created_at: string;
  command: { recognition_basis: string; unit_basis: string };
  snapshot: {
    act: { snapshot: { lines: { source: string; line_no: number }[] } };
    mapping: { line_source: string; account: string; lot: string; quantity: string; cost_byn: string; expense_account: string; expense_dimensions: Record<string,string> }[];
    commercial: { line_no: number; net_byn: string; vat_byn: string; gross_byn: string }[];
    pages: { entry_id: number }[];
  };
};

export function AccountingShipmentPackage({ org, entryId, onEntry }: { org: string; entryId: number; onEntry: (id: number) => void }) {
  const [data, setData] = useState<SavedPackage | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);

  async function show() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setOpen(true); setBusy(true); setError(""); setData(null);
    try {
      const response = await fetch(`/api/accounting/organizations/${org}/entries/${entryId}/shipment-package`, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(response.status === 409 ? "Сохранённый пакет не прошёл проверку. Обратитесь к главному бухгалтеру." : "Пакет недоступен: проверьте права и наличие проведённого пакета.");
      const result: SavedPackage = await response.json();
      if (String(result.organization_id) !== org || !result.snapshot.pages.some(page => page.entry_id === entryId)) throw new Error("Получен пакет другой операции.");
      if (!controller.signal.aborted) setData(result);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось получить пакет.");
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  return <div className="my-3 min-w-0 rounded-lg border border-line p-3">
    <Button variant="ghost" onClick={() => { if (open) { pending.current?.abort(); setOpen(false); setBusy(false); setData(null); } else void show(); }}>{open ? "Скрыть пакет отгрузки" : "Показать пакет отгрузки"}</Button>
    {open && <section aria-label="Пакет отгрузки" className="min-w-0 space-y-3 text-sm">
      {busy && <p role="status">Загружается сохранённый пакет…</p>}
      {error && <div><p role="alert">{error}</p><Button variant="ghost" onClick={() => void show()}>Повторить загрузку</Button></div>}
      {data && <>
        <p className="text-muted">Сохранённый расчёт. Нормативная и налоговая проверка не подтверждена.</p>
        <AccountingSourceLink org={org} source={data.source} />
        <dl className="grid gap-2 sm:grid-cols-2">
          <div><dt className="text-muted">Зарегистрировал</dt><dd>{data.actor} · {data.created_at}</dd></div>
          <div><dt className="text-muted">Основание признания</dt><dd>{data.command.recognition_basis}</dd></div>
          <div><dt className="text-muted">Единицы учёта</dt><dd>{data.command.unit_basis}</dd></div>
        </dl>
        <div className="flex flex-wrap gap-3" aria-label="Страницы пакета">{data.snapshot.pages.map((page, index) => <button key={page.entry_id} type="button" className="text-accent underline" disabled={page.entry_id === entryId} onClick={() => onEntry(page.entry_id)}>Страница {index + 1} · операция № {page.entry_id}</button>)}</div>
        <div className="max-w-full overflow-x-auto"><table className="w-full text-left"><caption className="text-left font-semibold">Количество и себестоимость</caption><thead><tr>{["Строка счёта", "Партия", "Количество", "Стоимость, BYN", "Списание", "Аналитика расхода"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead>
          <tbody>{data.snapshot.mapping.map((row, index) => <tr key={index} className="border-t border-line"><td className="p-2">{data.snapshot.act.snapshot.lines.find(line => line.source === row.line_source)?.line_no ?? "Не получено"}</td><td className="p-2">{row.lot}</td><td className="p-2 tabular-nums">{row.quantity}</td><td className="p-2 tabular-nums">{row.cost_byn}</td><td className="p-2">Кт {row.account} → Дт {row.expense_account}</td><td className="p-2">{Object.entries(row.expense_dimensions).map(([key,value]) => `${key}: ${value}`).join("; ") || "Без аналитики"}</td></tr>)}</tbody>
        </table></div>
        <div className="max-w-full overflow-x-auto"><table className="w-full text-left"><caption className="text-left font-semibold">Продажа и НДС, BYN</caption><thead><tr>{["Строка счёта", "Без НДС", "НДС", "Всего"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{data.snapshot.commercial.map(row => <tr key={row.line_no} className="border-t border-line"><td className="p-2">{row.line_no}</td><td className="p-2">{row.net_byn}</td><td className="p-2">{row.vat_byn}</td><td className="p-2">{row.gross_byn}</td></tr>)}</tbody></table></div>
      </>}
    </section>}
  </div>;
}
