"use client";

import clsx from "clsx";
import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import { filterByWarehouse, fetchStockMirror, type StockMirror } from "@/lib/wms-stock";
import { type StockThreshold } from "@/lib/wms-warehouse";

export function WmsStockView({
  initial,
  thresholds,
}: {
  initial: StockMirror;
  thresholds: StockThreshold[];
}) {
  const [data, setData] = useState<StockMirror>(initial);
  const [warehouse, setWarehouse] = useState("");
  const [busy, setBusy] = useState(false);

  const thresholdMap = useMemo(() => {
    const m = new Map<string, number>();
    for (const t of thresholds) {
      if (t.active) m.set(`${t.sku_code}:${t.warehouse}`, t.min_qty);
    }
    return m;
  }, [thresholds]);

  async function refresh() {
    setBusy(true);
    setData(await fetchStockMirror());
    setBusy(false);
  }

  const rows = useMemo(() => filterByWarehouse(data.rows, warehouse), [data.rows, warehouse]);
  const tabCls = (active: boolean) =>
    clsx("rounded-md px-3 py-1.5 text-sm font-medium", active ? "bg-surface text-accent-ink shadow-sm" : "text-muted");

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted">
          Остатки по складам — <b>зеркало 1С</b> (только чтение). Строки с{" "}
          <span className="font-medium text-red-600">дефицитом</span> выделены — свободный остаток
          ниже порога.
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

      <div className="mt-4 inline-flex rounded-lg border border-line bg-sunken p-1">
        <button onClick={() => setWarehouse("")} className={tabCls(warehouse === "")}>
          Все склады
        </button>
        {data.warehouses.map((w) => (
          <button key={w} onClick={() => setWarehouse(w)} className={tabCls(warehouse === w)}>
            {w}
          </button>
        ))}
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 font-medium">Номенклатура</th>
              <th className="px-4 py-2 font-medium">Зона/Ячейка</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 text-right font-medium">Резерв</th>
              <th className="px-4 py-2 text-right font-medium">Доступно</th>
              <th className="px-4 py-2 text-right font-medium">Порог</th>
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
            {rows.map((r, i) => {
              const minQty = thresholdMap.get(`${r.sku_code}:${r.warehouse}`);
              const belowMin = minQty !== undefined && r.qty_free < minQty;
              return (
                <tr
                  key={`${r.sku_code}-${r.warehouse}-${i}`}
                  className={clsx(
                    "border-b border-line last:border-0",
                    belowMin && "bg-red-50 dark:bg-red-950/20",
                  )}
                >
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                  <td className="px-4 py-2.5 text-ink">{r.title}</td>
                  <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                  <td className="px-4 py-2.5 text-right font-semibold tabular-nums text-ink">
                    {formatNumber(r.qty_available)}{" "}
                    <span className="text-faint">{r.unit}</span>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-amber-600">
                    {r.qty_reserved ? formatNumber(r.qty_reserved) : "—"}
                  </td>
                  <td
                    className={clsx(
                      "px-4 py-2.5 text-right font-semibold tabular-nums",
                      belowMin ? "text-red-600" : r.qty_free > 0 ? "text-green-600" : "text-faint",
                    )}
                  >
                    {formatNumber(r.qty_free)}
                  </td>
                  <td
                    className={clsx(
                      "px-4 py-2.5 text-right tabular-nums",
                      belowMin ? "font-semibold text-red-600" : "text-muted",
                    )}
                  >
                    {minQty !== undefined ? formatNumber(minQty) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {data.truncated && (
        <p className="mt-3 text-xs text-faint">
          Показаны не все SKU — уточните фильтр.
        </p>
      )}
    </div>
  );
}
