"use client";

import clsx from "clsx";
import { AlertTriangle, MapPin, Send, Sparkles, Truck, X } from "lucide-react";
import { useState } from "react";

import { formatByn, formatNumber } from "@/lib/format";
import {
  CARRIER_THRESHOLD_KG,
  CARRIERS,
  classifyTracking,
  parseWeightKg,
  requiresCarrierRequest,
  summarizeDeliveries,
  type Delivery,
  type TrackingTone,
} from "@/lib/office-delivery";

const TONE: Record<TrackingTone, string> = {
  slate: "bg-slate-100 text-slate-500",
  violet: "bg-violet-50 text-violet-600",
  blue: "bg-blue-50 text-blue-600",
  green: "bg-emerald-50 text-emerald-600",
  red: "bg-red-50 text-red-600",
};

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className={clsx("mt-1 text-2xl font-bold", tone ?? "text-ink")}>{value}</div>
    </div>
  );
}

function StageBadge({ stage }: { stage: Delivery["stage"] }) {
  const meta = classifyTracking(stage);
  return (
    <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", TONE[meta.tone])}>
      {meta.label}
    </span>
  );
}

/** Модалка «Заявка перевозчику» — открывается только для тяжёлых отгрузок (гард ≥300 кг). */
function CarrierRequestModal({
  delivery,
  onClose,
  onSubmit,
}: {
  delivery: Delivery;
  onClose: () => void;
  onSubmit: (carrier: string) => void;
}) {
  const kg = parseWeightKg(delivery.weight);
  const [carrier, setCarrier] = useState(CARRIERS[0]);
  const [eta, setEta] = useState(delivery.eta ?? "");
  const [comment, setComment] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-pop"
      >
        <div className="flex items-start justify-between gap-2 border-b border-slate-200 px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-100 text-brand-600">
              <Truck size={18} />
            </span>
            <div>
              <h3 className="font-bold text-ink">Заявка перевозчику</h3>
              <div className="text-xs text-muted">
                Отгрузка № {delivery.code} · {delivery.company}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="shrink-0 text-slate-400 hover:text-slate-600" aria-label="Закрыть">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-sm text-amber-700">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>
              Вес <b>{formatNumber(kg)} кг</b> ≥ {CARRIER_THRESHOLD_KG} кг — нужна заявка перевозчику
              (самовывозом/курьером не отправить).
            </span>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Перевозчик</span>
            <select
              value={carrier}
              onChange={(e) => setCarrier(e.target.value)}
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            >
              {CARRIERS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Желаемая дата подачи</span>
            <input
              value={eta}
              onChange={(e) => setEta(e.target.value)}
              placeholder="напр. 12.06"
              className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-slate-500">Комментарий</span>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              rows={2}
              placeholder="Адрес, контактное лицо, упаковка…"
              className="w-full resize-none rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
            />
          </label>
        </div>

        <div className="flex justify-end gap-2 border-t border-slate-200 px-5 py-3.5">
          <button
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50"
          >
            Отмена
          </button>
          <button
            onClick={() => onSubmit(carrier)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            <Send size={16} /> Отправить заявку
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Секция «Доставка и трекинг» офис-менеджера: статусы отгрузок, BYN-суммы и
 * модалка заявки перевозчику с гардом ≥300 кг. Данные и назначение перевозчика
 * держит родитель (office-view) — секция презентационная + форма модалки.
 */
export function OfficeDelivery({
  deliveries,
  onAssignCarrier,
}: {
  deliveries: Delivery[];
  onAssignCarrier: (id: number, carrier: string) => void;
}) {
  const [modalFor, setModalFor] = useState<Delivery | null>(null);
  const s = summarizeDeliveries(deliveries);

  return (
    <main className="flex-1 overflow-auto p-6">
      <div>
        <h1 className="text-xl font-bold text-ink">Доставка и трекинг</h1>
        <p className="mt-0.5 text-sm text-muted">
          Отгрузки после сборки: статус, перевозчик, суммы в BYN. Тяжёлые (≥{CARRIER_THRESHOLD_KG} кг)
          требуют заявку перевозчику.
        </p>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
        <Kpi label="Всего отгрузок" value={String(s.total)} />
        <Kpi label="В пути" value={String(s.inTransit)} tone="text-blue-600" />
        <Kpi label="Доставлено" value={String(s.delivered)} tone="text-emerald-600" />
        <Kpi label="Задержки" value={String(s.delayed)} tone="text-red-600" />
        <Kpi label="Сумма к отгрузке" value={formatByn(s.totalAmount)} tone="text-ink" />
      </div>

      {s.needCarrierRequest > 0 && (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-amber-100 bg-amber-50/60 p-3 text-sm text-amber-800">
          <Sparkles size={16} className="mt-0.5 shrink-0 text-amber-500" />
          <span>
            <span className="font-semibold">AI-инсайт: </span>
            {s.needCarrierRequest} тяжёлых отгрузок (≥{CARRIER_THRESHOLD_KG} кг) ещё без перевозчика —
            оформите заявки, чтобы не сорвать сроки.
          </span>
        </div>
      )}

      <div className="mt-5 overflow-hidden rounded-xl border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2.5 font-medium">№</th>
              <th className="px-4 py-2.5 font-medium">Компания</th>
              <th className="px-4 py-2.5 font-medium">Назначение</th>
              <th className="px-4 py-2.5 font-medium">Вес</th>
              <th className="px-4 py-2.5 font-medium">Сумма</th>
              <th className="px-4 py-2.5 font-medium">Статус</th>
              <th className="px-4 py-2.5 font-medium">Перевозчик</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">
                  Отгрузок пока нет
                </td>
              </tr>
            )}
            {deliveries.map((d) => (
              <tr key={d.id} className="border-b border-slate-50 last:border-0">
                <td className="px-4 py-3 text-slate-500">{d.code}</td>
                <td className="px-4 py-3 font-medium text-ink">{d.company}</td>
                <td className="px-4 py-3 text-slate-600">
                  <span className="inline-flex items-center gap-1">
                    <MapPin size={13} className="text-slate-400" />
                    {d.destination ?? "—"}
                    {d.eta && <span className="text-xs text-muted">· {d.eta}</span>}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-600">{formatNumber(parseWeightKg(d.weight))} кг</td>
                <td className="px-4 py-3 font-medium text-ink">{formatByn(d.amount)}</td>
                <td className="px-4 py-3">
                  <StageBadge stage={d.stage} />
                </td>
                <td className="px-4 py-3">
                  {d.carrier ? (
                    <span className="inline-flex items-center gap-1.5 text-slate-700">
                      <Truck size={14} className="text-emerald-500" />
                      {d.carrier}
                    </span>
                  ) : requiresCarrierRequest(d.weight) ? (
                    <button
                      onClick={() => setModalFor(d)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-100"
                    >
                      <Truck size={14} /> Заявка перевозчику
                    </button>
                  ) : (
                    <span className="text-xs text-muted">курьер / самовывоз</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modalFor && (
        <CarrierRequestModal
          delivery={modalFor}
          onClose={() => setModalFor(null)}
          onSubmit={(carrier) => {
            onAssignCarrier(modalFor.id, carrier);
            setModalFor(null);
          }}
        />
      )}
    </main>
  );
}
