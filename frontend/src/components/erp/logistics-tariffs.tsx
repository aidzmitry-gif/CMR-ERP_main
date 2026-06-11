"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { quoteTariff } from "@/lib/logistics-domain";
import {
  fetchTariffs,
  fetchZones,
  seedTariffs,
  seedZones,
  type CarrierTariff,
  type Zone,
} from "@/lib/logistics-api";
import { formatByn } from "@/lib/format";

export function LogisticsTariffs() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [zone, setZone] = useState<string>("");
  const [tariffs, setTariffs] = useState<CarrierTariff[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // параметры калькулятора котировки
  const [weight, setWeight] = useState(8);
  const [declaredValue, setDeclaredValue] = useState(0);
  const [cod, setCod] = useState(false);

  async function loadZones() {
    const z = await fetchZones();
    setZones(z);
    if (z.length > 0) setZone((cur) => cur || z[0].code);
    setLoading(false);
  }

  useEffect(() => {
    void loadZones();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!zone) return;
    void fetchTariffs(zone).then(setTariffs);
  }, [zone]);

  async function onSeed() {
    setBusy(true);
    await seedZones();
    await seedTariffs();
    await loadZones();
    if (zone) setTariffs(await fetchTariffs(zone));
    setBusy(false);
  }

  if (loading) return <Loading />;
  if (zones.length === 0)
    return <EmptyState text="Зоны доставки и тарифы ещё не заданы." onSeed={onSeed} busy={busy} />;

  const quotes = tariffs.map((t) => ({
    tariff: t,
    price: quoteTariff(t, weight, { declaredValue: declaredValue || undefined, cod }),
  }));
  const cheapest = quotes.reduce<number | null>(
    (min, q) => (min === null || q.price < min ? q.price : min),
    null,
  );

  return (
    <div className="space-y-4">
      <Card
        title="Зоны доставки"
        action={<GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>}
      >
        <div className="flex flex-wrap gap-2">
          {zones.map((z) => (
            <button
              key={z.code}
              onClick={() => setZone(z.code)}
              className={
                z.code === zone
                  ? "rounded-lg border border-brand bg-blue-50 px-3 py-2 text-left text-sm"
                  : "rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:bg-slate-50"
              }
            >
              <div className="font-medium text-ink">{z.name}</div>
              <div className="text-[11px] text-muted">
                {z.coverage} · SLA {z.sla_days_min}–{z.sla_days_max} дн
              </div>
            </button>
          ))}
        </div>
      </Card>

      <Card
        title="Калькулятор котировки"
        hint="Цена по тарифам выбранной зоны для заданного веса (страховка и наложенный платёж — опционально)."
      >
        <div className="flex flex-wrap items-end gap-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Вес, кг</span>
            <input
              type="number"
              min={0}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value))}
              className="w-28 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Ценность груза (BYN)</span>
            <input
              type="number"
              min={0}
              value={declaredValue}
              onChange={(e) => setDeclaredValue(Number(e.target.value))}
              className="w-36 rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            />
          </label>
          <label className="flex items-center gap-2 pb-2.5 text-sm text-slate-600">
            <input type="checkbox" checked={cod} onChange={(e) => setCod(e.target.checked)} />
            Наложенный платёж
          </label>
        </div>

        {tariffs.length === 0 ? (
          <p className="mt-4 text-sm text-muted">Для этой зоны тарифов нет.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-slate-100 text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Перевозчик</th>
                  <th className="px-3 py-2 text-right font-medium">до 5 кг</th>
                  <th className="px-3 py-2 text-right font-medium">до 10 кг</th>
                  <th className="px-3 py-2 text-right font-medium">до 30 кг</th>
                  <th className="px-3 py-2 text-right font-medium">&gt;30, за кг</th>
                  <th className="px-3 py-2 text-right font-medium">Забор</th>
                  <th className="px-3 py-2 text-right font-medium">Котировка</th>
                </tr>
              </thead>
              <tbody>
                {quotes.map(({ tariff: t, price }) => (
                  <tr key={t.carrier_code} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td className="px-3 py-2 font-medium text-ink">{t.carrier_code}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(t.price_w5)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(t.price_w10)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(t.price_w30)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(t.over30_per_kg)}</td>
                    <td className="px-3 py-2 text-right tabular-nums text-slate-600">{formatByn(t.pickup_fee)}</td>
                    <td className="px-3 py-2 text-right">
                      <span className="inline-flex items-center gap-2">
                        <span className="font-semibold tabular-nums text-ink">{formatByn(price)}</span>
                        {price === cheapest && <Pill text="дешевле" tone="emerald" />}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
