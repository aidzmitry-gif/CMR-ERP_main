"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, KpiTile, Loading, Pill } from "@/components/erp/logistics-ui";
import {
  awardRfq,
  fetchCostInsights,
  seedAudit,
  seedRfq,
  seedTariffs,
  seedZones,
  type CostInsights,
} from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

const WEIGHTS = [5, 10, 30, 100];

/** Тон пилюли разброса: больше разброс → больше потенциал экономии (внимание). */
function spreadTone(pct: number): "slate" | "emerald" | "amber" | "blue" {
  if (pct >= 20) return "amber";
  if (pct >= 8) return "blue";
  return "emerald";
}

export function LogisticsInsights() {
  const [weight, setWeight] = useState(30);
  const [data, setData] = useState<CostInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  async function load(w: number) {
    setData(await fetchCostInsights(w));
    setLoading(false);
  }

  useEffect(() => {
    void fetchCostInsights(weight).then((data) => {
      setData(data);
      setLoading(false);
    });
  }, [weight]);

  async function onSeed() {
    setBusy(true);
    await seedZones();
    await seedTariffs();
    await seedAudit();
    const rfq = await seedRfq();
    if (rfq) await awardRfq(rfq.id); // заключаем демо-тендер → появляется экономия торга
    await load(weight);
    setBusy(false);
  }

  if (loading) return <Loading />;

  const zones = data?.zones ?? [];
  if (zones.length === 0)
    return (
      <EmptyState
        text="Нет данных для аналитики стоимости. Засейте зоны, тарифы, аудит и демо-тендер."
        onSeed={onSeed}
        busy={busy}
      />
    );

  const tenders = data?.tenders ?? [];
  const recs = data?.recommendations ?? [];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <KpiTile
          label="Потенциал по зонам"
          value={formatByn(data?.potential_savings ?? 0)}
          sub={`выбор дешёвого vs среднего на ${data?.reference_weight_kg ?? weight} кг`}
          tone="brand"
        />
        <KpiTile
          label="Экономия торга"
          value={formatByn(data?.tender_savings_total ?? 0)}
          sub="старт − выигравшая ставка"
          tone="emerald"
        />
        <KpiTile
          label="К возврату (аудит)"
          value={formatByn(data?.audit_to_recover ?? 0)}
          tone={(data?.audit_to_recover ?? 0) > 0 ? "red" : "emerald"}
        />
      </div>

      {recs.length > 0 && (
        <Card title="Рекомендации" hint="Как снизить стоимость перевозок (на накопленных данных)">
          <ul className="space-y-2">
            {recs.map((r, i) => (
              <li key={i} className="flex gap-2 text-sm text-muted">
                <span className="text-accent-ink">→</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card
        title="Разброс тарифов по зонам"
        hint="Самый дешёвый перевозчик и потенциал экономии на эталонный вес"
        action={
          <div className="flex items-center gap-1">
            {WEIGHTS.map((w) => (
              <button
                key={w}
                onClick={() => setWeight(w)}
                className={
                  "rounded-lg px-2.5 py-1.5 text-xs font-medium " +
                  (w === weight ? "bg-accent text-white" : "border border-line text-muted hover:bg-sunken")
                }
              >
                {w} кг
              </button>
            ))}
            <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>
          </div>
        }
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Зона</th>
                <th className="px-3 py-2 font-medium">Перевозчиков</th>
                <th className="px-3 py-2 font-medium">Дешевле всех</th>
                <th className="px-3 py-2 text-right font-medium">Мин</th>
                <th className="px-3 py-2 text-right font-medium">Средний</th>
                <th className="px-3 py-2 text-right font-medium">Макс</th>
                <th className="px-3 py-2 font-medium">Разброс</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
                <tr
                  key={z.zone_code}
                  className={
                    "border-b border-line last:border-0 hover:bg-sunken " +
                    (z.zone_code === data?.best_savings_zone ? "bg-amber-50/40" : "")
                  }
                >
                  <td className="px-3 py-2 text-ink">
                    {z.zone_code}
                    <span className="ml-1 text-xs text-muted">{z.zone_name}</span>
                  </td>
                  <td className="px-3 py-2 text-muted">{z.carriers}</td>
                  <td className="px-3 py-2 font-medium text-emerald-700">{z.cheapest_carrier_name}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-emerald-600">{formatByn(z.cheapest_total)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{formatByn(z.avg_total)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-faint">{formatByn(z.max_total)}</td>
                  <td className="px-3 py-2">
                    <Pill text={`${z.spread_pct.toFixed(0)}%`} tone={spreadTone(z.spread_pct)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {tenders.length > 0 && (
        <Card title="Экономия по заключённым тендерам" hint="Снижение цены торгом: стартовая → выигравшая">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Тендер</th>
                  <th className="px-3 py-2 font-medium">Маршрут</th>
                  <th className="px-3 py-2 font-medium">Перевозчик</th>
                  <th className="px-3 py-2 text-right font-medium">Старт</th>
                  <th className="px-3 py-2 text-right font-medium">Выиграл</th>
                  <th className="px-3 py-2 text-right font-medium">Сэкономлено</th>
                </tr>
              </thead>
              <tbody>
                {tenders.map((t) => (
                  <tr key={t.rfq_number} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-3 py-2 text-muted">{t.rfq_number}</td>
                    <td className="px-3 py-2 text-muted">{t.route}</td>
                    <td className="px-3 py-2 text-muted">{t.carrier}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-faint">{formatByn(t.baseline)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-ink">{formatByn(t.awarded)}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums text-emerald-600">
                      {formatByn(t.saved)} <span className="text-xs text-emerald-500">({t.saved_pct.toFixed(0)}%)</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
