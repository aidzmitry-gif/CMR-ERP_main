"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, GradeBadge, Loading } from "@/components/erp/logistics-ui";
import { computeScorecardScore, scoreGrade } from "@/lib/logistics-domain";
import {
  fetchAudit,
  fetchScorecard,
  seedScorecard,
  type AuditReport,
  type Scorecard,
} from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const DEFAULT_PERIOD = "2026-06";

export function LogisticsScorecard() {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [rows, setRows] = useState<Scorecard[]>([]);
  const [audit, setAudit] = useState<AuditReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function load(p: string) {
    const [scoreRows, auditReport] = await Promise.all([fetchScorecard(p), fetchAudit(p)]);
    setRows(scoreRows);
    setAudit(auditReport);
    setLoading(false);
  }

  useEffect(() => {
    void load(period);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period]);

  async function onSeed() {
    setBusy(true);
    await seedScorecard();
    await load(period);
    setBusy(false);
  }

  // Переплаты по счетам (из аудита, событие freight.audit_refund) в разрезе перевозчика.
  const overpayByCarrier = new Map<string, number>();
  for (const it of audit?.items ?? []) {
    if (it.variance > 0)
      overpayByCarrier.set(it.carrier_code, (overpayByCarrier.get(it.carrier_code) ?? 0) + it.variance);
  }

  if (loading) return <Loading />;
  if (rows.length === 0)
    return <EmptyState text={`Scorecard за ${period} ещё не рассчитан.`} onSeed={onSeed} busy={busy} />;

  // Балл/грейд от backend — основной; при отсутствии считаем на клиенте из метрик.
  const scored = rows
    .map((r) => {
      const score = r.score || computeScorecardScore(r);
      return { ...r, score, grade: r.grade || scoreGrade(score) };
    })
    .sort((a, b) => b.score - a.score);

  return (
    <Card
      title="Scorecard перевозчиков"
      hint="OTD/OTIF, сохранность, точность счетов, претензии → взвешенный балл и грейд A/B/C."
      action={
        <div className="flex items-center gap-2">
          <input
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="ГГГГ-ММ"
            className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
          />
          <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>
        </div>
      }
    >
      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Перевозчик</th>
              <th className="px-3 py-2 text-right font-medium">OTD</th>
              <th className="px-3 py-2 text-right font-medium">OTIF</th>
              <th className="px-3 py-2 text-right font-medium">Сохранность</th>
              <th className="px-3 py-2 text-right font-medium">Точн. счетов</th>
              <th className="px-3 py-2 text-right font-medium">Претензии</th>
              <th className="px-3 py-2 text-right font-medium">Стоимость дост.</th>
              <th className="px-3 py-2 text-right font-medium" title="Переплаты по счетам за период (аудит)">
                Переплаты
              </th>
              <th className="px-3 py-2 text-right font-medium">Балл</th>
              <th className="px-3 py-2 text-center font-medium">Грейд</th>
            </tr>
          </thead>
          <tbody>
            {scored.map((r) => {
              const overpay = overpayByCarrier.get(r.carrier_code) ?? 0;
              return (
                <tr key={r.carrier_code} className="border-b border-line last:border-0 hover:bg-sunken">
                  <td className="px-3 py-2 font-medium text-ink">{r.carrier_code}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{r.otd_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{r.otif_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{r.damage_free_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{r.billing_accuracy_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{r.claims_ratio_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{formatByn(r.cost_per_delivery)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {overpay > 0 ? (
                      <span className="font-medium text-red-600" title="К возврату по аудиту счетов">
                        {formatByn(overpay)}
                      </span>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">{r.score}</td>
                  <td className="px-3 py-2 text-center">
                    <GradeBadge grade={r.grade} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {audit && audit.to_recover > 0 && (
        <p className="mt-2 text-xs text-muted">
          Всего к возврату за {period}:{" "}
          <span className="font-semibold text-red-600">{formatByn(audit.to_recover)}</span> — разбор на вкладке
          «Аудит счетов».
        </p>
      )}
    </Card>
  );
}
