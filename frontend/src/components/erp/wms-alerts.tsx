"use client";

import clsx from "clsx";
import { AlertTriangle, Loader2, PackagePlus } from "lucide-react";
import { useState } from "react";

import { SourceTag } from "@/components/source-tag";
import { formatNumber } from "@/lib/format";
import {
  type Alerts,
  alertsEmitMessage,
  canEmitAlerts,
  emitAlerts,
  severityLabel,
} from "@/lib/wms-warehouse";

type EmitState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; message: string }
  | { kind: "error" };

export function WmsAlerts({ initial }: { initial: Alerts }) {
  const d = initial;
  const [state, setState] = useState<EmitState>({ kind: "idle" });
  const canEmit = canEmitAlerts(d);

  async function onEmit() {
    setState({ kind: "loading" });
    const res = await emitAlerts();
    if (res === null) {
      setState({ kind: "error" });
      return;
    }
    setState({ kind: "success", message: alertsEmitMessage(res.emitted) });
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-muted">
          Дефицит: свободный остаток <SourceTag entity="" source="1c" /> ниже порога. Источник
          остатка — 1С. Заявку в закупку оформляем сигналом{" "}
          <code className="rounded bg-sunken px-1 text-xs">wms.stock.low</code> — Закупки заводят
          черновик (модули связаны событием, не напрямую).
        </p>
        <button
          type="button"
          onClick={onEmit}
          disabled={!canEmit || state.kind === "loading"}
          className={clsx(
            "inline-flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
            canEmit
              ? "bg-accent text-white hover:opacity-90"
              : "cursor-not-allowed border border-line bg-sunken text-faint",
          )}
          title={canEmit ? "Отправить сигнал дозаказа в закупки" : "Нет нарушенных порогов"}
        >
          {state.kind === "loading" ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <PackagePlus size={15} />
          )}
          Создать заявку в закупку
        </button>
      </div>

      {state.kind === "success" && (
        <div className="mt-3 rounded-xl border border-green-300 bg-green-50 px-4 py-2.5 text-sm text-green-700">
          {state.message}
        </div>
      )}
      {state.kind === "error" && (
        <div className="mt-3 rounded-xl border border-red-300 bg-red-50 px-4 py-2.5 text-sm text-red-700">
          Не удалось отправить сигнал — источник остатка (1С) не подключён или сервис недоступен.
        </div>
      )}

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
              </tr>
            </thead>
            <tbody>
              {d.rows.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-6 text-center text-muted">
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
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
