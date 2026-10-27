"use client";

import { useEffect, useRef, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { quoteTariff } from "@/lib/logistics-domain";
import {
  fetchTariffs,
  fetchZones,
  logisticsReadMessage,
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
  const [zonesError, setZonesError] = useState<string | null>(null);
  const [zonesAttempt, setZonesAttempt] = useState(0);
  const [tariffsLoading, setTariffsLoading] = useState(true);
  const [tariffsError, setTariffsError] = useState<string | null>(null);
  const [tariffsAttempt, setTariffsAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const zoneScope = useRef(zone);
  const writing = useRef(false);

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
    if (writing.current || !editing) return;
    const targetZone = zone;
    setTariffError(null);
    const patch: TariffPatch = {};
    for (const key of ["price_w5", "price_w10", "price_w30", "over30_per_kg", "pickup_fee"] as const) {
      const raw = draft[key]?.trim() ?? "";
      const v = Number(raw.replace(",", "."));
      if (!/^(?:\d+(?:[.,]\d+)?|[.,]\d+)$/.test(raw) || !Number.isFinite(v)) {
        setTariffError("Заполните все ставки неотрицательными числами. Неверное поле не будет пропущено."); return;
      }
      patch[key] = v;
    }
    writing.current = true; setBusy(true);
    try {
    const updated = await patchTariff(carrierCode, targetZone, patch);
    if (!updated) {
      setTariffError("Не удалось сохранить тариф.");
      return;
    }
    setEditing(null);
    try {
      const rows = await fetchTariffs(targetZone);
      if (zoneScope.current === targetZone) setTariffs(rows);
    } catch (error) {
      if (zoneScope.current === targetZone) {
        setTariffs([]);
        setTariffsError(`Тариф сохранён, но список не обновлён. ${logisticsReadMessage(error)}`);
      }
    }
    } catch { setTariffError("Сохранение тарифа не подтверждено. Проверьте результат перед повтором."); }
    finally { writing.current = false; setBusy(false); }
  }

  function cancelEdit() {
    setEditing(null);
    setDraft({});
    setTariffError(null);
  }

  async function loadZones() {
    const z = await fetchZones();
    setZonesError(null);
    setZones(z);
    setZone((cur) => z.some(item => item.code === cur) ? cur : z[0]?.code ?? "");
    setTariffs([]);
    setTariffsError(null);
    setTariffsLoading(true);
    setTariffsAttempt(n => n + 1);
    setLoading(false);
  }

  useEffect(() => {
    let alive = true;
    void fetchZones().then((z) => {
      if (!alive) return;
      setZones(z);
      setZone((cur) => z.some(item => item.code === cur) ? cur : z[0]?.code ?? "");
      setTariffs([]);
      setTariffsError(null);
      setTariffsLoading(true);
      setTariffsAttempt(n => n + 1);
    }).catch((error: unknown) => {
      if (alive) setZonesError(logisticsReadMessage(error));
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => { alive = false; };
  }, [zonesAttempt]);

  useEffect(() => {
    zoneScope.current = zone;
    if (!zone) return;
    let alive = true;
    void fetchTariffs(zone).then(rows => { if (alive) setTariffs(rows); })
      .catch((error: unknown) => { if (alive) setTariffsError(logisticsReadMessage(error)); })
      .finally(() => { if (alive) setTariffsLoading(false); });
    return () => { alive = false; };
  }, [zone, tariffsAttempt]);

  async function onSeed() {
    setBusy(true);
    setTariffs([]);
    setTariffsError(null);
    setTariffsLoading(true);
    try {
      await seedZones();
      await seedTariffs();
      await loadZones();
    } catch (error) {
      setZonesError(logisticsReadMessage(error));
    } finally { setBusy(false); }
  }

  if (loading) return <Loading />;
  if (zonesError) return (
    <div className="rounded-xl bg-surface p-6 shadow-card">
      <p role="alert" className="text-sm text-muted">{zonesError}</p>
      <GhostButton onClick={() => { setLoading(true); setZonesError(null); setZonesAttempt(n => n + 1); }}>Повторить загрузку</GhostButton>
    </div>
  );
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
        action={!tariffsError && !tariffsLoading ? <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton> : undefined}
      >
        <div className="flex flex-wrap gap-2">
          {zones.map((z) => (
            <button
              key={z.code}
              disabled={busy}
              onClick={() => { if (writing.current || z.code === zone) return; cancelEdit(); setTariffs([]); setTariffsLoading(true); setTariffsError(null); setZone(z.code); }}
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
        {tariffsLoading ? <Loading /> : tariffsError ? (
          <div>
            <p role="alert" className="text-sm text-muted">{tariffsError}</p>
            <GhostButton onClick={() => { setTariffsLoading(true); setTariffsError(null); setTariffsAttempt(n => n + 1); }}>Повторить загрузку тарифов</GhostButton>
          </div>
        ) : <>
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
        </>}
      </Card>
    </div>
  );
}
