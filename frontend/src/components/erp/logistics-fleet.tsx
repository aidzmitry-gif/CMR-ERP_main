"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, GhostButton, Loading, Pill } from "@/components/erp/logistics-ui";
import { vehicleFits } from "@/lib/logistics-domain";
import {
  createCarrier,
  fetchCargoCapabilities,
  fetchCarriers,
  fetchEligible,
  fetchVehicles,
  seedCarriers,
  seedFleet,
  type CargoCapability,
  type Carrier,
  type EligibleCarrier,
  type Vehicle,
} from "@/lib/logistics-api";
import { formatNumber } from "@/lib/format";

export function LogisticsFleet() {
  const [carriers, setCarriers] = useState<Carrier[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [selected, setSelected] = useState<string | null>(null);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [caps, setCaps] = useState<CargoCapability[]>([]);

  // подбор перевозчика под груз
  const [weight, setWeight] = useState(500);
  const [needsTemp, setNeedsTemp] = useState(false);
  const [eligible, setEligible] = useState<EligibleCarrier[] | null>(null);

  // форма добавления перевозчика
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [newCode, setNewCode] = useState("");
  const [newKind, setNewKind] = useState("РБ");
  const [newMode, setNewMode] = useState("авто");
  const [addError, setAddError] = useState<string | null>(null);

  async function onAddCarrier() {
    setAddError(null);
    if (!newName.trim()) {
      setAddError("Название обязательно.");
      return;
    }
    setBusy(true);
    const created = await createCarrier({
      name: newName.trim(),
      code: newCode.trim(),
      kind: newKind,
      mode: newMode,
    });
    setBusy(false);
    if (!created) {
      setAddError("Не удалось добавить перевозчика.");
      return;
    }
    setNewName("");
    setNewCode("");
    setAdding(false);
    await loadCarriers();
  }

  async function loadCarriers() {
    setCarriers(await fetchCarriers());
    setLoading(false);
  }

  useEffect(() => {
    void fetchCarriers().then((carriers) => {
      setCarriers(carriers);
      setLoading(false);
    });
  }, []);

  async function onSeed() {
    setBusy(true);
    await seedCarriers();
    await seedFleet();
    await loadCarriers();
    setBusy(false);
  }

  async function openCarrier(code: string) {
    setSelected(code);
    const [v, c] = await Promise.all([fetchVehicles(code), fetchCargoCapabilities(code)]);
    setVehicles(v);
    setCaps(c);
  }

  async function findEligible() {
    setEligible(await fetchEligible({ weight_kg: weight, needs_temp: needsTemp }));
  }

  if (loading) return <Loading />;
  if (carriers.length === 0)
    return <EmptyState text="Перевозчики и парк ещё не заведены." onSeed={onSeed} busy={busy} />;

  return (
    <div className="space-y-4">
      <Card
        title="Подбор перевозчика под груз"
        hint="Запрос к backend по грузоподъёмности и температурному режиму."
      >
        <div className="flex flex-wrap items-end gap-4">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">Вес, кг</span>
            <input
              type="number"
              min={0}
              value={weight}
              onChange={(e) => setWeight(Number(e.target.value))}
              className="w-32 rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>
          <label className="flex items-center gap-2 pb-2.5 text-sm text-muted">
            <input type="checkbox" checked={needsTemp} onChange={(e) => setNeedsTemp(e.target.checked)} />
            Нужен холод (реф)
          </label>
          <button
            onClick={findEligible}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink"
          >
            Подобрать
          </button>
        </div>
        {eligible && (
          <div className="mt-3">
            {eligible.length === 0 ? (
              <p className="text-sm text-muted">Подходящих перевозчиков не найдено.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {eligible.map((e) => (
                  <span
                    key={`${e.carrier_code}-${e.vehicle_class}`}
                    className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-sm text-emerald-700"
                  >
                    {e.carrier} · {e.vehicle_class} ({formatNumber(e.capacity_kg)} кг)
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </Card>

      <Card
        title="Перевозчики"
        action={
          <div className="flex flex-wrap gap-2">
            <GhostButton onClick={() => setAdding((v) => !v)} busy={busy}>
              {adding ? "Отмена" : "+ Добавить"}
            </GhostButton>
            <GhostButton onClick={onSeed} busy={busy}>Обновить демо</GhostButton>
          </div>
        }
      >
        {adding && (
          <div className="mb-4 rounded-lg border border-line bg-sunken p-3">
            {addError && (
              <p className="mb-2 text-xs text-red-600">{addError}</p>
            )}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <label className="block text-xs text-muted">
                Название
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="напр. ООО «Перевозкин»"
                  className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                />
              </label>
              <label className="block text-xs text-muted">
                Код (slug)
                <input
                  value={newCode}
                  onChange={(e) => setNewCode(e.target.value)}
                  placeholder="напр. perevozkin"
                  className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                />
              </label>
              <label className="block text-xs text-muted">
                Тип
                <select
                  value={newKind}
                  onChange={(e) => setNewKind(e.target.value)}
                  className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                >
                  <option value="РБ">РБ</option>
                  <option value="РФ">РФ</option>
                  <option value="импорт">импорт</option>
                </select>
              </label>
              <label className="block text-xs text-muted">
                Транспорт
                <select
                  value={newMode}
                  onChange={(e) => setNewMode(e.target.value)}
                  className="mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                >
                  <option value="авто">авто</option>
                  <option value="море">море</option>
                  <option value="ж/д">ж/д</option>
                  <option value="авиа">авиа</option>
                </select>
              </label>
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={onAddCarrier}
                disabled={busy}
                className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
              >
                Добавить
              </button>
            </div>
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-line text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Перевозчик</th>
                <th className="px-3 py-2 font-medium">Тип</th>
                <th className="px-3 py-2 text-right font-medium">В срок</th>
                <th className="px-3 py-2 text-right font-medium">Ср. срок</th>
                <th className="px-3 py-2 text-right font-medium">Отгрузок</th>
                <th className="px-3 py-2 font-medium">Статус</th>
              </tr>
            </thead>
            <tbody>
              {carriers.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => openCarrier(c.code)}
                  className={
                    "cursor-pointer border-b border-line last:border-0 hover:bg-sunken " +
                    (selected === c.code ? "bg-blue-50/50" : "")
                  }
                >
                  <td className="px-3 py-2 font-medium text-ink">{c.name}</td>
                  <td className="px-3 py-2 text-muted">
                    {c.kind} · {c.mode}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{c.on_time_pct}%</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{c.avg_days} дн</td>
                  <td className="px-3 py-2 text-right tabular-nums text-muted">{c.shipments_count}</td>
                  <td className="px-3 py-2">
                    <Pill text={c.active ? "активен" : "выкл"} tone={c.active ? "emerald" : "slate"} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && (
        <Card title={`Парк и допуски · ${selected}`}>
          <div className="grid gap-5 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Транспорт</div>
              {vehicles.length === 0 ? (
                <p className="text-sm text-muted">Нет данных по парку.</p>
              ) : (
                <ul className="space-y-1.5">
                  {vehicles.map((v) => {
                    const fits = vehicleFits(v, { weight_kg: weight, needs_temp: needsTemp });
                    return (
                      <li
                        key={v.vehicle_class}
                        className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-sm"
                      >
                        <span className="text-ink">
                          {v.vehicle_class} · {formatNumber(v.capacity_kg)} кг · {v.volume_m3} м³
                          {v.temp_control && " · реф"}
                        </span>
                        <span className="flex items-center gap-2 text-muted">
                          ×{v.count}
                          {fits && <Pill text="под груз" tone="emerald" />}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
            <div>
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Категории грузов</div>
              {caps.length === 0 ? (
                <p className="text-sm text-muted">Нет данных по допускам.</p>
              ) : (
                <ul className="space-y-1.5">
                  {caps.map((c) => (
                    <li
                      key={c.category}
                      className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-sm"
                    >
                      <span className="text-ink">{c.category}</span>
                      <span className="flex items-center gap-1.5">
                        {c.adr && <Pill text="ADR" tone="amber" />}
                        {c.oversize && <Pill text="негабарит" tone="violet" />}
                        <span className="text-muted">до {formatNumber(c.max_weight_kg)} кг</span>
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
