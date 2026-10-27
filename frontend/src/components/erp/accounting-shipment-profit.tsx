"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

type Amounts = { revenue_net_byn: string; cogs_byn: string; gross_profit_byn: string; margin_percent: string | null };
type Row = Amounts & { receipt_id: number; entry_id: number; document_id: number; operation_date: string; posting_date: string; items: { sku: string; quantity: string }[] };
type Report = { organization_id: number; start: string; end: string; rows: Row[]; page_subtotal: Amounts; has_more: boolean; offset: number; basis: string };

export function AccountingShipmentProfit({ org, start, end, onEntry }: { org: string; start: string; end: string; onEntry: (id: number) => void }) {
  return <ProfitReport key={`${org}/${start}/${end}`} org={org} start={start} end={end} onEntry={onEntry} />;
}

function ProfitReport({ org, start, end, onEntry }: { org: string; start: string; end: string; onEntry: (id: number) => void }) {
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [loaded, setLoaded] = useState<{ offset: number; reload: number; report: Report | null; error: string } | null>(null);
  const active = loaded?.offset === offset && loaded?.reload === reload ? loaded : null;
  useEffect(() => {
    if (!org) return;
    let alive = true;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/accounting/organizations/${org}/reports/shipment-profit?start=${start}&end=${end}&offset=${offset}&limit=100`, { cache: "no-store", signal: controller.signal });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Не удалось загрузить прибыль по отгрузкам.");
        if (String(data.organization_id) !== org || data.start !== start || data.end !== end || data.offset !== offset || data.basis !== "at_posting" || !Array.isArray(data.rows)) throw new Error("Ответ не соответствует организации и периоду отчёта.");
        if (alive) setLoaded({ offset, reload, report: data, error: "" });
      } catch (e) { if (alive) setLoaded({ offset, reload, report: null, error: (e as Error).message }); }
    })();
    return () => { alive = false; controller.abort(); };
  }, [org, start, end, offset, reload]);
  const report = active?.report;
  const cells = (row: Amounts) => <><td className="p-2 text-right">{row.revenue_net_byn}</td><td className="p-2 text-right">{row.cogs_byn}</td><td className="p-2 text-right">{row.gross_profit_byn}</td><td className="p-2 text-right">{row.margin_percent === null ? "—" : `${row.margin_percent}%`}</td></>;
  return <section aria-label="Валовая прибыль по отгрузкам" className="space-y-4 rounded-xl border border-line bg-surface p-4">
    <h2 className="font-semibold">Валовая прибыль по отгрузкам</h2>
    <p>Период отгрузки: {start} — {end}. Суммы в BYN.</p>
    <p className="text-sm text-muted">Выручка без НДС минус себестоимость, зафиксированная при проведении каждой отгрузки. Текущие закупочные цены не меняют эти значения. Это прибыль на момент проведения: последующие корректировки затрат и возвраты здесь не учтены. Непроведённые отгрузки появятся после проведения.</p>
    {!org ? <p>Выберите организацию.</p> : !active ? <p role="status">Загрузка отчёта…</p> : active.error ? <p role="alert" className="text-red-700">{active.error}</p> : null}
    <Button variant="secondary" disabled={!org || !active} onClick={() => setReload(value => value + 1)}>Обновить отчёт</Button>
    {report && (!report.rows.length ? <p>{offset === 0 ? "За выбранный период проведённых отгрузок нет." : "На этой странице отгрузок нет. Вернитесь на предыдущую страницу."}</p> : <>
      <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr>{["Отгрузка / счёт", "Товары", "Выручка без НДС", "Себестоимость", "Валовая прибыль", "Валовая маржа"].map(label => <th className="p-2 text-left" key={label}>{label}</th>)}</tr></thead><tbody>
        {report.rows.map(row => <tr key={row.receipt_id} className="border-t border-line"><td className="p-2"><Button variant="secondary" onClick={() => onEntry(row.entry_id)}>Отгрузка № {row.receipt_id}</Button><p>{row.operation_date} · счёт № {row.document_id}</p></td><td className="p-2">{row.items.map((item, i) => <div key={i}>{item.sku} × {item.quantity}</div>)}</td>{cells(row)}</tr>)}
      </tbody><tfoot><tr className="border-t border-line font-semibold"><td colSpan={2} className="p-2">Итого на странице</td>{cells(report.page_subtotal)}</tr></tfoot></table></div>
    </>)}
    {org && <div className="flex items-center gap-3"><Button variant="secondary" disabled={offset === 0 || !active} onClick={() => setOffset(value => Math.max(0, value - 100))}>Назад</Button><span>Страница {offset / 100 + 1}</span><Button variant="secondary" disabled={!report?.has_more} onClick={() => setOffset(value => value + 100)}>Далее</Button></div>}
  </section>;
}
