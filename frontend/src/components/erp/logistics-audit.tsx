"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, KpiTile, Loading, Pill } from "@/components/erp/logistics-ui";
import { auditSummary, auditVariance } from "@/lib/logistics-domain";
import { fetchAudit, seedAudit, type AuditEntry, type AuditReport } from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const DEFAULT_PERIOD = "2026-06";

const STATUS_TONE: Record<string, "slate" | "blue" | "emerald" | "amber"> = {
  ok: "emerald",
  open: "amber",
  recovered: "emerald",
  disputed: "amber",
};

export function LogisticsAudit() {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [report, setReport] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function load(p: string) {
    setReport(await fetchAudit(p));
    setLoading(false);
  }

  useEffect(() => {
    void load(period);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  async function onSeed() {
    setBusy(true);
    await seedAudit();
    await load(period);
    setBusy(false);
  }

  if (loading) return <Loading />;

  const items: AuditEntry[] = report?.items ?? [];
  if (items.length === 0)
    return <EmptyState text={`Аудит счетов за ${period} ещё не проводился.`} onSeed={onSeed} busy={busy} />;

  // Свод от backend — основной; при отсутствии считаем из позиций (та же доменная логика).
  const summary = auditSummary(items);
  const checked = report?.checked ?? summary.checked;
  const discrepancies = report?.discrepancies ?? summary.discrepancies;
  const toRecover = report?.to_recover ?? summary.toRecover;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <KpiTile label="Проверено счетов" value={checked} />
        <KpiTile label="Расхождений" value={discrepancies} tone={discrepancies > 0 ? "amber" : "emerald"} />
        <KpiTile label="К возврату" value={formatByn(toRecover)} tone={toRecover > 0 ? "red" : "emerald"} />
      </div>

      <Card
        title="Аудит счетов перевозчиков"
        hint="Сверка выставленного счёта с ожидаемым по тарифу; переплаты — к возврату."
        action={
          <div className="flex items-center gap-2">
            <input
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="ГГГГ-ММ"
              className="w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            />
            <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-slate-100 text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Отгрузка</th>
                <th className="px-3 py-2 font-medium">Перевозчик</th>
                <th className="px-3 py-2 text-right font-medium">Счёт</th>
                <th className="px-3 py-2 text-right font-medium">Ожидалось</th>
                <th className="px-3 py-2 text-right font-medium">Отклонение</th>
                <th className="px-3 py-2 font-medium">Причина</th>
                <th className="px-3 py-2 font-medium">Статус</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const variance = auditVariance(it.invoice_amount, it.expected_amount);
                return (
                  <tr key={it.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-3 py-2 text-muted">{it.shipment_code}</td>
                    <td className="px-3 py-2 text-slate-600">{it.carrier_code}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink">{formatByn(it.invoice_amount)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(it.expected_amount)}</td>
                    <td
                      className={
                        "px-3 py-2 text-right font-semibold tabular-nums " +
                        (variance > 0 ? "text-red-600" : variance < 0 ? "text-emerald-600" : "text-slate-400")
                      }
                    >
                      {variance > 0 ? "+" : ""}
                      {formatByn(variance)}
                    </td>
                    <td className="px-3 py-2 text-slate-600">{it.reason}</td>
                    <td className="px-3 py-2">
                      <Pill text={it.status} tone={STATUS_TONE[it.status] ?? "slate"} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
