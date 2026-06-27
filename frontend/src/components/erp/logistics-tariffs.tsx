"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { quoteTariff } from "@/lib/logistics-domain";
import {
  fetchTariffs,
  fetchZones,
  patchTariff,
  seedTariffs,
  seedZones,
  type CarrierTariff,
  type TariffPatch,
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

  // правка тарифа inline
  const [editing, setEditing] = useState<string | null>(null);    // carrier_code
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [tariffError, setTariffError] = useState<string | null>(null);

  function startEdit(t: CarrierTariff) {
    setEditing(t.carrier_code);
    setDraft({
      price_w5: String(t.price_w5),
      price_w10: String(t.price_w10),
      price_w30: String(t.price_w30),
      over30_per_kg: String(t.over30_per_kg),
      pickup_fee: String(t.pickup_fee),
    });
    setTariffError(null);
  }

  async function saveEdit(carrierCode: string) {
    setTariffError(null);
    const patch: TariffPatch = {};
    for (const key of ["price_w5", "price_w10", "price_w30", "over30_per_kg", "pickup_fee"] as const) {
      const v = parseFloat(draft[key]);
      if (Number.isFinite(v) && v >= 0) patch[key] = v;
    }
    setBusy(true);
    const updated = await patchTariff(carrierCode, zone, patch);
    setBusy(false);
    if (!updated) {
      setTariffError("Не удалось сохранить тариф.");
      return;
    }
    setEditing(null);
    setTariffs(await fetchTariffs(zone));
  }

  function cancelEdit() {
    setEditing(null);
    setDraft({});
    setTariffError(null);
  }

  async function loadZones() {
    const z = await fetchZones();
    setZones(z);
    if (z.length > 0) setZone((cur) => cur || z[0].code);
    setLoading(false);
  }

  useEffect(() => {
    void fetchZones().then((z) => {
      setZones(z);
      if (z.length > 0) setZone((cur) => cur || z[0].code);
      setLoading(false);
    });
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
                  ? "rounded-lg border border-accent bg-blue-50 px-3 py-2 text-left text-sm"
                  : "rounded-lg border border-line bg-surface px-3 py-2 text-left text-sm hover:bg-sunken"
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
            <span className="mb-1 block text-xs font-medium text-muted">Вес, кг</span>
            <input
              type="number"
              min={0}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value))}
              className="w-28 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">Ценность груза (BYN)</span>
            <input
              type="number"
              min={0}
              value={declaredValue}
              onChange={(e) => setDeclaredValue(Number(e.target.value))}
              className="w-36 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="flex items-center gap-2 pb-2.5 text-sm text-muted">
            <input type="checkbox" checked={cod} onChange={(e) => setCod(e.target.checked)} />
            Наложенный платёж
          </label>
        </div>

        {tariffs.length === 0 ? (
          <p className="mt-4 text-sm text-muted">Для этой зоны тарифов нет.</p>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="border-b border-line text-left text-xs text-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">Перевозчик</th>
                  <th className="px-3 py-2 text-right font-medium">до 5 кг</th>
                  <th className="px-3 py-2 text-right font-medium">до 10 кг</th>
                  <th className="px-3 py-2 text-right font-medium">до 30 кг</th>
                  <th className="px-3 py-2 text-right font-medium">&gt;30, за кг</th>
                  <th className="px-3 py-2 text-right font-medium">Забор</th>
                  <th className="px-3 py-2 text-right font-medium">Котировка</th>
                  <th className="px-3 py-2 text-right font-medium" aria-label="Действие" />
                </tr>
              </thead>
              <tbody>
                {quotes.map(({ tariff: t, price }) => {
                  const isEditing = editing === t.carrier_code;
                  const numField = (key: keyof TariffPatch & string) => (
                    <input
                      type="number"
                      step="0.1"
                      value={draft[key] ?? ""}
                      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                      className="w-20 rounded border border-line bg-surface px-1.5 py-1 text-right text-sm text-ink outline-none focus:border-accent"
                    />
                  );
                  return (
                    <tr key={t.carrier_code} className="border-b border-line last:border-0 hover:bg-sunken">
                      <td className="px-3 py-2 font-medium text-ink">{t.carrier_code}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted">
                        {isEditing ? numField("price_w5") : formatByn(t.price_w5)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted">
                        {isEditing ? numField("price_w10") : formatByn(t.price_w10)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted">
                        {isEditing ? numField("price_w30") : formatByn(t.price_w30)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted">
                        {isEditing ? numField("over30_per_kg") : formatByn(t.over30_per_kg)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-muted">
                        {isEditing ? numField("pickup_fee") : formatByn(t.pickup_fee)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="inline-flex items-center gap-2">
                          <span className="font-semibold tabular-nums text-ink">{formatByn(price)}</span>
                          {price === cheapest && <Pill text="дешевле" tone="emerald" />}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {isEditing ? (
                          <span className="inline-flex gap-1">
                            <button
                              onClick={() => saveEdit(t.carrier_code)}
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
                            onClick={() => startEdit(t)}
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
        )}
        {tariffError && (
          <p className="mt-2 text-xs text-red-600">{tariffError}</p>
        )}
      </Card>
    </div>
  );
}
