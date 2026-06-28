"use client";

import clsx from "clsx";

import { SourceTag } from "@/components/source-tag";
import { formatByn, formatNumber } from "@/lib/format";
import type { Reconciliation } from "@/lib/wms-warehouse";

export function WmsReconciliation({ initial }: { initial: Reconciliation }) {
  const d = initial;
  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Сверка оперативного остатка WMS (из движений) с зеркалом 1С. Расхождение — сигнал к
        разбору; в 1С ничего не пишем. Сверху — где сильнее расходятся деньги.
      </p>

      {!d.gateway ? (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Источник 1С не подключён — сверка недоступна.
        </div>
      ) : (
        <>
          <div className="mt-4 rounded-xl border border-line bg-surface px-4 py-3">
            <div className="text-xs font-medium text-muted">Суммарное расхождение в деньгах</div>
            <div className={clsx("mt-1 text-2xl font-bold tabular-nums", d.total_abs_diff_value ? "text-red-600" : "text-ink")}>
              {formatByn(d.total_abs_diff_value)}
            </div>
          </div>

          <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-2 font-medium">Код</th>
                  <th className="px-4 py-2 font-medium">Номенклатура</th>
                  <th className="px-4 py-2 font-medium">Склад</th>
                  <th className="px-4 py-2 text-right font-medium">WMS</th>
                  <th className="px-4 py-2 text-right font-medium">
                    1С <SourceTag entity="" source="1c" />
                  </th>
                  <th className="px-4 py-2 text-right font-medium">Δ</th>
                  <th className="px-4 py-2 text-right font-medium">Δ в деньгах</th>
                </tr>
              </thead>
              <tbody>
                {d.rows.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-6 text-center text-muted">Расхождений нет — WMS сходится с 1С</td></tr>
                )}
                {d.rows.map((r, i) => (
                  <tr key={`${r.sku_code}-${r.warehouse}-${i}`} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                    <td className="px-4 py-2.5 text-ink">{r.title || "—"}</td>
                    <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(r.wms_qty)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(r.onec_qty)}</td>
                    <td className={clsx("px-4 py-2.5 text-right tabular-nums font-semibold", r.diff === 0 ? "text-faint" : "text-red-600")}>
                      {r.diff > 0 ? `+${formatNumber(r.diff)}` : formatNumber(r.diff)}
                    </td>
                    <td className={clsx("px-4 py-2.5 text-right tabular-nums font-semibold", r.diff_value ? "text-red-600" : "text-faint")}>
                      {r.diff_value === null ? "—" : formatByn(r.diff_value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
