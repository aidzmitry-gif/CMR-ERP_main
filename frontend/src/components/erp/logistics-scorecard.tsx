"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, GradeBadge, Loading } from "@/components/erp/logistics-ui";
import { computeScorecardScore, scoreGrade } from "@/lib/logistics-domain";
import {
  fetchAudit,
  fetchScorecard,
  patchScorecardMetrics,
  recomputeScorecard,
  seedScorecard,
  type AuditReport,
  type Scorecard,
  type ScorecardMetricsPatch,
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

  const [editing, setEditing] = useState<string | null>(null);     // carrier_code or null
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  function startEdit(r: Scorecard) {
    setEditing(r.carrier_code);
    setDraft({
      otd_pct: String(r.otd_pct),
      otif_pct: String(r.otif_pct),
      damage_free_pct: String(r.damage_free_pct),
      billing_accuracy_pct: String(r.billing_accuracy_pct),
      claims_ratio_pct: String(r.claims_ratio_pct),
    });
    setSaveError(null);
  }

  function cancelEdit() {
    setEditing(null);
    setDraft({});
    setSaveError(null);
  }

  async function saveEdit(carrierCode: string) {
    setSaveError(null);
    const patch: ScorecardMetricsPatch = {};
    for (const key of ["otd_pct", "otif_pct", "damage_free_pct", "billing_accuracy_pct", "claims_ratio_pct"] as const) {
      const v = parseFloat(draft[key]);
      if (Number.isFinite(v)) patch[key] = v;
    }
    setBusy(true);
    const updated = await patchScorecardMetrics(carrierCode, period, patch);
    setBusy(false);
    if (!updated) {
      setSaveError("Не удалось сохранить KPI.");
      return;
    }
    setEditing(null);
    setDraft({});
    await load(period);
  }

  async function onRecompute() {
    setBusy(true);
    await recomputeScorecard();
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
          <GhostButton onClick={onRecompute} busy={busy}>Пересчитать</GhostButton>
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
              <th className="px-3 py-2 text-right font-medium" aria-label="Действия" />
            </tr>
          </thead>
          <tbody>
            {scored.map((r) => {
              const overpay = overpayByCarrier.get(r.carrier_code) ?? 0;
              const isEditing = editing === r.carrier_code;
              const field = (key: keyof ScorecardMetricsPatch & string) => (
                <input
                  type="number"
                  step="0.1"
                  value={draft[key] ?? ""}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                  className="w-20 rounded border border-line bg-surface px-1.5 py-1 text-right text-sm text-ink outline-none focus:border-accent"
                />
              );
              return (
                <tr key={r.carrier_code} className="border-b border-line last:border-0 hover:bg-sunken">
                  <td className="px-3 py-2 font-medium text-ink">{r.carrier_code}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {isEditing ? field("otd_pct") : `${r.otd_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {isEditing ? field("otif_pct") : `${r.otif_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {isEditing ? field("damage_free_pct") : `${r.damage_free_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {isEditing ? field("billing_accuracy_pct") : `${r.billing_accuracy_pct}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">
                    {isEditing ? field("claims_ratio_pct") : `${r.claims_ratio_pct}%`}
                  </td>
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
                  <td className="px-3 py-2 text-right">
                    {isEditing ? (
                      <span className="inline-flex gap-1">
                        <button
                          onClick={() => saveEdit(r.carrier_code)}
                          disabled={busy}
                          className="rounded border border-accent bg-accent px-2 py-0.5 text-xs font-medium text-white hover:bg-accent-ink disabled:opacity-60"
                        >
                          ✓
                        </button>
                        <button
                          onClick={cancelEdit}
                          disabled={busy}
                          className="rounded border border-line bg-surface px-2 py-0.5 text-xs text-muted hover:bg-sunken"
                        >
                          ✕
                        </button>
                      </span>
                    ) : (
                      <button
                        onClick={() => startEdit(r)}
                        className="text-xs text-accent-ink hover:underline"
                      >
                        ✏
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {saveError && (
        <p className="mt-2 text-xs text-red-600">{saveError}</p>
      )}
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
