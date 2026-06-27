"use client";

import clsx from "clsx";
import { AlertTriangle } from "lucide-react";

import { SourceTag } from "@/components/source-tag";
import { formatNumber } from "@/lib/format";
import { type Alerts, severityLabel } from "@/lib/wms-warehouse";

export function WmsAlerts({ initial }: { initial: Alerts }) {
  const d = initial;
  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Дефицит: свободный остаток <SourceTag entity="" source="1c" /> ниже порога. Источник
        остатка — 1С; заявку в закупку отсюда не создаём (граница модулей).
      </p>

      {!d.gateway ? (
        <div className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Источник 1С не подключён — дефицит не рассчитан.
        </div>
      ) : (
        <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-4 py-2 font-medium">Код</th>
                <th className="px-4 py-2 font-medium">Номенклатура</th>
                <th className="px-4 py-2 font-medium">Склад</th>
                <th className="px-4 py-2 text-right font-medium">Свободно</th>
                <th className="px-4 py-2 text-right font-medium">Минимум</th>
                <th className="px-4 py-2 text-right font-medium">Дефицит</th>
                <th className="px-4 py-2 text-right font-medium">Дозаказ</th>
                <th className="px-4 py-2 font-medium">Статус</th>
                <th className="px-4 py-2 text-right font-medium" />
              </tr>
            </thead>
            <tbody>
              {d.rows.length === 0 && (
                <tr><td colSpan={9} className="px-4 py-6 text-center text-muted">
                  <AlertTriangle size={20} className="mx-auto mb-1 text-faint" />
                  Дефицита нет — все остатки выше порогов
                </td></tr>
              )}
              {d.rows.map((r) => (
                <tr key={`${r.sku_code}-${r.warehouse}`} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                  <td className="px-4 py-2.5 text-ink">{r.title || "—"}</td>
                  <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(r.free_qty)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(r.min_qty)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums font-semibold text-red-600">{formatNumber(r.deficit)}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-muted">{formatNumber(r.reorder_qty)}</td>
                  <td className="px-4 py-2.5">
                    <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      r.severity === "out_of_stock" ? "bg-red-50 text-red-600" : "bg-amber-50 text-amber-600")}>
                      {severityLabel(r.severity)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {/* TODO: связать с закупкой через событие/ручку (граница модулей — не дёргаем procurement напрямую) */}
                    <button
                      title="Передать в закупку (в разработке)"
                      className="rounded-lg border border-line px-2 py-1 text-xs text-muted hover:bg-sunken"
                      onClick={() => alert("Заявка в закупку — в разработке (через событие, не напрямую)")}
                    >
                      В закупку
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
