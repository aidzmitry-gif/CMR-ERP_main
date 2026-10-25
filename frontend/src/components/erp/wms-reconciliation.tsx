"use client";

import clsx from "clsx";
import { useEffect, useState } from "react";

import { InstanceOrganizationGate } from "@/components/instance-organization-gate";
import { SourceTag } from "@/components/source-tag";
import { formatByn, formatNumber } from "@/lib/format";
import { fetchRecon, type Reconciliation } from "@/lib/wms-warehouse";

export function ScopedWmsReconciliation() {
  return <InstanceOrganizationGate>{organization => <CompanyReconciliation key={organization.id} organizationId={organization.id} />}</InstanceOrganizationGate>;
}

function CompanyReconciliation({ organizationId }: { organizationId: number }) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{ loading: boolean; data: Reconciliation | null }>({ loading: true, data: null });
  useEffect(() => {
    const controller = new AbortController();
    void fetchRecon(organizationId, controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ loading: false, data });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ loading: false, data: null });
    });
    return () => controller.abort();
  }, [organizationId, attempt]);
  if (state.loading) return <p role="status" className="p-6">Загрузка движений компании…</p>;
  return <WmsReconciliation initial={state.data} onRetry={() => {
    setState({ loading: true, data: null }); setAttempt(value => value + 1);
  }} />;
}

export function WmsReconciliation({ initial, onRetry }: { initial: Reconciliation | null; onRetry?: () => void }) {
  if (!initial) return <div className="p-6">
    <p role="alert">Не удалось загрузить сверку компании. Остатки и расхождения неизвестны.</p>
    <button type="button" onClick={onRetry ?? (() => window.location.reload())} className="mt-3 rounded-lg border border-line px-3 py-2">Повторить загрузку</button>
  </div>;
  const d = initial;
  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Оперативные количества из журнала движений компании. Для сверки с 1С нужен
        подтверждённый источник остатков этой компании; в 1С ничего не пишем.
      </p>

      {!d.gateway && (
        <div role="status" className="mt-4 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          {d.source_unavailable_reason === "stock_gateway_unavailable"
            ? "Источник остатков недоступен. Сравнение с 1С не выполнено."
            : "Источник остатков 1С не подтверждён для этой компании. Сравнение и денежная оценка неизвестны."}
        </div>
      )}
          <div className="mt-4 rounded-xl border border-line bg-surface px-4 py-3">
            <div className="text-xs font-medium text-muted">Суммарное расхождение в деньгах</div>
            <div className={clsx("mt-1 text-2xl font-bold tabular-nums", d.total_abs_diff_value ? "text-red-600" : "text-ink")}>
              {d.total_abs_diff_value === null ? "Неизвестно" : formatByn(d.total_abs_diff_value)}
            </div>
          </div>

          <div className="mt-4 overflow-x-auto rounded-xl border border-line bg-surface">
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
                  <tr><td colSpan={7} className="px-4 py-6 text-center text-muted">Движения компании не найдены. Сверка с 1С не подтверждена.</td></tr>
                )}
                {d.rows.map((r, i) => (
                  <tr key={`${r.sku_code}-${r.warehouse}-${i}`} className="border-b border-line last:border-0">
                    <td className="px-4 py-2.5 font-mono text-xs text-muted">{r.sku_code}</td>
                    <td className="px-4 py-2.5 text-ink">{r.title || "—"}</td>
                    <td className="px-4 py-2.5 text-muted">{r.warehouse}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(r.wms_qty)}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{r.onec_qty === null ? "—" : formatNumber(r.onec_qty)}</td>
                    <td className={clsx("px-4 py-2.5 text-right tabular-nums font-semibold", r.diff === null || r.diff === 0 ? "text-faint" : "text-red-600")}>
                      {r.diff === null ? "—" : r.diff > 0 ? `+${formatNumber(r.diff)}` : formatNumber(r.diff)}
                    </td>
                    <td className={clsx("px-4 py-2.5 text-right tabular-nums font-semibold", r.diff_value ? "text-red-600" : "text-faint")}>
                      {r.diff_value === null ? "—" : formatByn(r.diff_value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
    </div>
  );
}
