"use client";

import clsx from "clsx";
import { RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  fetchStockMirror,
  filterByQuery,
  filterByWarehouse,
  type StockMirror,
  stockTotals,
} from "@/lib/wms-stock";

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="mt-1 text-2xl font-bold text-ink tabular-nums">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-faint">{hint}</div>}
    </div>
  );
}

export function WmsStockTable({ initial }: { initial: StockMirror }) {
  const [data, setData] = useState<StockMirror>(initial);
  const [warehouse, setWarehouse] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // первичные данные пришли с SSR; тихо перечитываем актуальное зеркало на клиенте
    void fetchStockMirror().then(setData);
  }, []);

  async function refresh() {
    setBusy(true);
    setData(await fetchStockMirror());
    setBusy(false);
  }

  const rows = useMemo(
    () => filterByQuery(filterByWarehouse(data.rows, warehouse), query),
    [data.rows, warehouse, query],
  );
  const totals = useMemo(() => stockTotals(rows), [rows]);

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Остатки и резервы по складам — <b>зеркало 1С</b> (только чтение). Источник истины
          остатка — 1С; склад отображает, не изменяет.
        </p>
        <button
          onClick={refresh}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-sm font-medium text-muted hover:bg-sunken disabled:opacity-60"
        >
          <RefreshCw size={15} className={clsx(busy && "animate-spin")} /> Обновить
        </button>
      </div>

      {!data.gateway && (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Источник остатков (1С / integrations) не подключён — данные недоступны.
        </div>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Позиций (SKU)" value={formatNumber(totals.skuCount)} />
        <Kpi label="Всего на складах" value={formatNumber(totals.available)} />
        <Kpi label="В резерве" value={formatNumber(totals.reserved)} />
        <Kpi label="Свободно к продаже" value={formatNumber(totals.free)} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-line bg-sunken p-1">
          <button
            onClick={() => setWarehouse("")}
            className={clsx(
              "rounded-md px-3 py-1.5 text-sm font-medium",
              warehouse === "" ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
            )}
          >
            Все склады
          </button>
          {data.warehouses.map((w) => (
            <button
              key={w}
              onClick={() => setWarehouse(w)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-sm font-medium",
                warehouse === w ? "bg-surface text-accent-ink shadow-sm" : "text-muted",
              )}
            >
              {w}
            </button>
          ))}
        </div>
        <div className="relative ml-auto">
          <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по коду или названию"
            className="w-64 rounded-lg border border-line bg-surface py-2 pl-8 pr-3 text-sm text-ink outline-none focus:border-accent"
          />
        </div>
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 text-right font-medium">Всего</th>
              <th className="px-4 py-2 text-right font-medium">Резерв</th>
              <th className="px-4 py-2 text-right font-medium">Свободно</th>
              <th className="px-4 py-2 text-right font-medium">Ожидается</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-muted">
                  {data.gateway ? "Остатков по фильтру нет" : "Нет данных об остатках"}
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={`${r.sku_code}-${r.warehouse}-${i}`} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                <td className="px-4 py-2.5 text-ink">{r.title}</td>
                <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-ink">
                  {formatNumber(r.qty_available)} <span className="text-faint">{r.unit}</span>
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-amber-600">
                  {r.qty_reserved ? formatNumber(r.qty_reserved) : "—"}
                </td>
                <td
                  className={clsx(
                    "px-4 py-2.5 text-right font-semibold tabular-nums",
                    r.qty_free > 0 ? "text-green-600" : "text-faint",
                  )}
                >
                  {formatNumber(r.qty_free)}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums text-muted">
                  {r.qty_forecast ? formatNumber(r.qty_forecast) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.truncated && (
        <p className="mt-3 text-xs text-faint">
          Показаны не все SKU (выборка ограничена) — уточните поиск.
        </p>
      )}
    </div>
  );
}
