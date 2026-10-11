"use client";

import clsx from "clsx";
import { RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import { type Balances, fetchBalances } from "@/lib/wms-ops";

export function WmsBalances({ initial }: { initial: Balances }) {
  const [data, setData] = useState<Balances>(initial);
  const [query, setQuery] = useState("");
  const [organization, setOrganization] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setBusy(true);
    try {
      setData(await fetchBalances());
      setError(false);
    } catch {
      setError(true);
    } finally {
      setBusy(false);
    }
  }

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return data.rows.filter(
      (r) => (!organization || String(r.organization_id ?? "unknown") === organization)
        && (!warehouse || JSON.stringify(r.warehouse) === warehouse)
        && (!q || `${r.sku_code} ${r.sku_title} ${r.location_code} ${r.batch_ref}`.toLowerCase().includes(q)),
    );
  }, [data.rows, query, organization, warehouse]);
  const organizations = Array.from(new Set(data.rows.map((r) => String(r.organization_id ?? "unknown")))).sort();
  const warehouses = Array.from(new Set(data.rows.map((r) => r.warehouse))).sort();

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Оперативный остаток <b>из движений WMS</b> (приход − расход). Полнота остатков зависит от переноса начальных данных и проведения всех складских операций. Отрицательные значения = аномалия журнала.
          {" "}Включены движения доступных юрлиц с подтверждённым владельцем. Движения без владельца требуют сопоставления и в этот расчёт не входят.
        </p>
        <div className="flex items-center gap-2">
          <Link
            href="/erp/wms/stock"
            className="rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken"
          >
            Сверка с остатками 1С →
          </Link>
          <button
            onClick={refresh}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
          >
            <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
          </button>
        </div>
      </div>

      {error && <p role="alert" className="mt-4 text-sm text-red-600">Не удалось обновить остатки. Показаны ранее загруженные данные. Повторите загрузку.</p>}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Код, название, ячейка или партия"
            aria-label="Поиск остатков по коду, названию, ячейке или партии"
            className="w-64 rounded-lg border border-line bg-surface py-2 pl-8 pr-3 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
        <select aria-label="Юрлицо остатков" value={organization} onChange={(e) => setOrganization(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
          <option value="">Все юрлица</option>
          {organizations.map((id) => <option key={id} value={id}>{id === "unknown" ? "Юрлицо не определено" : `Юрлицо №${id}`}</option>)}
        </select>
        <select aria-label="Склад остатков" value={warehouse} onChange={(e) => setWarehouse(e.target.value)} className="rounded-lg border border-line bg-surface px-3 py-2 text-sm">
          <option value="">Все склады</option>
          {warehouses.map((name) => <option key={name} value={JSON.stringify(name)}>{name || "Склад не указан"}</option>)}
        </select>
        <button type="button" onClick={() => { setQuery(""); setOrganization(""); setWarehouse(""); }} className="rounded-lg border border-line px-3 py-2 text-sm">Сбросить фильтры</button>
        <span className="text-xs text-faint">SKU: {data.sku_count}</span>
        <span className="text-xs text-faint">Строк: {rows.length} из {data.rows.length}</span>
      </div>

      <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Юрлицо</th>
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 font-medium">Ячейка</th>
              <th className="px-4 py-2 font-medium">Партия</th>
              <th className="px-4 py-2 text-right font-medium">Остаток</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  Нет строк по выбранным условиям
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={`${r.sku_code}-${r.location_id}-${r.batch_ref}-${i}`} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-muted">{r.organization_id ? `Юрлицо №${r.organization_id}` : "Не определено"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                <td className="px-4 py-2.5 text-ink">{r.sku_title || "—"}</td>
                <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                <td className="px-4 py-2.5 text-muted">{r.location_code || "—"}</td>
                <td className="px-4 py-2.5 text-faint">{r.batch_ref || "—"}</td>
                <td
                  className={clsx(
                    "px-4 py-2.5 text-right font-semibold tabular-nums",
                    r.qty < 0 ? "text-red-600" : "text-ink",
                  )}
                >
                  {formatNumber(r.qty)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
