"use client";

import { useState } from "react";

import { GhostButton, Pill } from "@/components/erp/logistics-ui";
import {
  patchShipmentStatus,
  patchShipmentTracking,
  type Shipment,
} from "@/lib/logistics-api";
import {
  allowedDeliveryTransitions,
  canTransitionDelivery,
  DELIVERY_FLOW,
  deliveryStatusLabel,
} from "@/lib/logistics-domain";
import { formatByn, formatNumber } from "@/lib/format";

// Карточка рейса + хронология статусов + ручной трекинг с экрана логиста.
// Бэк: PATCH /shipments/{id} (главный status, эмит shipment.delivered и др.) и
// PATCH /shipments/{id}/tracking (текст tracking_status + ETA, эмит delivery.tracking).
// Переходы статусов валидируются в logistics-domain (allowedDeliveryTransitions): назад
// двигаться нельзя; planned→delivered напрямую через assigned, не сразу.

const STATUS_TONE: Record<string, "slate" | "blue" | "amber" | "emerald"> = {
  planned: "slate",
  assigned: "blue",
  in_transit: "blue",
  at_customs: "amber",
  delivered: "emerald",
};

export function ShipmentDrawer({
  shipment,
  onClose,
  onUpdated,
}: {
  shipment: Shipment;
  onClose: () => void;
  onUpdated: (s: Shipment) => void;
}) {
  const [trackingText, setTrackingText] = useState(shipment.tracking_status ?? "");
  const [eta, setEta] = useState(shipment.eta ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const allowed = allowedDeliveryTransitions(shipment.status);

  async function setStatus(next: string) {
    if (!canTransitionDelivery(shipment.status, next)) return;
    setBusy(true);
    setError(null);
    const updated = await patchShipmentStatus(shipment.id, next);
    setBusy(false);
    if (!updated) {
      setError("Не удалось сменить статус. Попробуйте ещё раз.");
      return;
    }
    onUpdated(updated);
  }

  async function saveTracking() {
    setBusy(true);
    setError(null);
    const updated = await patchShipmentTracking(shipment.id, {
      tracking_status: trackingText,
      eta: eta || null,
    });
    setBusy(false);
    if (!updated) {
      setError("Не удалось сохранить трекинг.");
      return;
    }
    onUpdated(updated);
  }

  return (
    <div className="fixed inset-0 z-40 flex">
      <button
        type="button"
        aria-label="Закрыть"
        onClick={onClose}
        className="flex-1 bg-black/30"
      />
      <aside className="relative flex h-full w-full max-w-[520px] flex-col overflow-y-auto border-l border-line bg-surface shadow-pop">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-line bg-surface px-5 py-3">
          <div>
            <div className="text-xs text-muted">{shipment.number || `№ ${shipment.id}`}</div>
            <h3 className="font-semibold text-ink">{shipment.customer}</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-line bg-surface px-2.5 py-1 text-sm text-muted hover:bg-sunken"
          >
            Закрыть
          </button>
        </header>

        <div className="space-y-4 px-5 py-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-600">
              {error}
            </div>
          )}

          <section className="grid grid-cols-2 gap-3 text-sm">
            <Field label="Маршрут" value={`${shipment.route_from || "—"} → ${shipment.route_to || "—"}`} />
            <Field label="Перевозчик" value={shipment.carrier || "—"} />
            <Field label="Груз" value={shipment.cargo || "—"} />
            <Field label="Вес, кг" value={formatNumber(shipment.weight_kg)} />
            <Field label="Сумма" value={formatByn(shipment.amount)} />
            <Field label="Сделка" value={shipment.address || "—"} />
          </section>

          <section>
            <div className="mb-2 text-xs font-medium text-muted">Этапы доставки</div>
            <ol className="space-y-1.5">
              {DELIVERY_FLOW.map((stage) => {
                const isCurrent = stage === shipment.status;
                const isPast =
                  DELIVERY_FLOW.indexOf(stage as (typeof DELIVERY_FLOW)[number]) <
                  DELIVERY_FLOW.indexOf(shipment.status as (typeof DELIVERY_FLOW)[number]);
                const tone = isCurrent
                  ? "text-ink"
                  : isPast
                    ? "text-muted"
                    : "text-faint";
                return (
                  <li key={stage} className={`flex items-center gap-2 text-sm ${tone}`}>
                    <span
                      className={`inline-flex h-4 w-4 items-center justify-center rounded-full border ${
                        isCurrent
                          ? "border-accent bg-accent"
                          : isPast
                            ? "border-emerald-400 bg-emerald-50"
                            : "border-line"
                      }`}
                    />
                    {deliveryStatusLabel(stage)}
                    {isCurrent && (
                      <Pill text="сейчас" tone={STATUS_TONE[stage] ?? "slate"} />
                    )}
                  </li>
                );
              })}
            </ol>
          </section>

          <section>
            <div className="mb-2 text-xs font-medium text-muted">Сменить статус</div>
            {allowed.length === 0 ? (
              <p className="text-sm text-muted">Доставка завершена.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {allowed.map((next) => (
                  <button
                    key={next}
                    onClick={() => setStatus(next)}
                    disabled={busy}
                    className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium text-ink hover:bg-sunken disabled:opacity-60"
                  >
                    → {deliveryStatusLabel(next)}
                  </button>
                ))}
              </div>
            )}
          </section>

          <section>
            <div className="mb-2 text-xs font-medium text-muted">Ручной трекинг</div>
            <label className="block text-xs text-muted">
              Статус (текст от перевозчика)
              <input
                value={trackingText}
                onChange={(e) => setTrackingText(e.target.value)}
                placeholder="напр. «Прошла таможню, в пути на разгрузку»"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </label>
            <label className="mt-2 block text-xs text-muted">
              ETA
              <input
                value={eta}
                onChange={(e) => setEta(e.target.value)}
                placeholder="дд.мм или ГГГГ-ММ-ДД"
                className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </label>
            <div className="mt-2 flex justify-end">
              <GhostButton onClick={saveTracking} busy={busy}>
                Сохранить трекинг
              </GhostButton>
            </div>
            <p className="mt-1.5 text-[11px] text-faint">
              Сохранение публикует <code>logistics.delivery.tracking</code> для офиса; смена
              статуса на «Доставлено» — <code>logistics.shipment.delivered</code> (sales/office).
            </p>
          </section>
        </div>
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-ink">{value}</div>
    </div>
  );
}
