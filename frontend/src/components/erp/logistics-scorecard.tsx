"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, GradeBadge, Loading } from "@/components/erp/logistics-ui";
import { computeScorecardScore, scoreGrade } from "@/lib/logistics-domain";
import { fetchScorecard, seedScorecard, type Scorecard } from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const DEFAULT_PERIOD = "2026-06";

export function LogisticsScorecard() {
  const [period, setPeriod] = useState(DEFAULT_PERIOD);
  const [rows, setRows] = useState<Scorecard[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function load(p: string) {
    setRows(await fetchScorecard(p));
    setLoading(false);
  }

  useEffect(() => {
    void fetchScorecard(period).then((scoreRows) => {
      setRows(scoreRows);
      setLoading(false);
    });
  }, [period]);

  async function onSeed() {
    setBusy(true);
    await seedScorecard();
    await load(period);
    setBusy(false);
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
              <th className="px-3 py-2 text-right font-medium">Балл</th>
              <th className="px-3 py-2 text-center font-medium">Грейд</th>
            </tr>
          </thead>
          <tbody>
            {scored.map((r) => (
              <tr key={r.carrier_code} className="border-b border-line last:border-0 hover:bg-sunken">
                <td className="px-3 py-2 font-medium text-ink">{r.carrier_code}</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{r.otd_pct}%</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{r.otif_pct}%</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{r.damage_free_pct}%</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{r.billing_accuracy_pct}%</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{r.claims_ratio_pct}%</td>
                <td className="px-3 py-2 text-right tabular-nums text-muted">{formatByn(r.cost_per_delivery)}</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-ink">{r.score}</td>
                <td className="px-3 py-2 text-center">
                  <GradeBadge grade={r.grade} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
