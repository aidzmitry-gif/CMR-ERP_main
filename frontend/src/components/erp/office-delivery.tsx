"use client";

import clsx from "clsx";
import { AlertTriangle, MapPin, Send, Truck, X } from "lucide-react";
import { useState } from "react";

import { formatByn, formatNumber } from "@/lib/format";
import {
  canRequestCarrier,
  classifyTracking,
  parseWeightKg,
  summarizeDeliveries,
  type Delivery,
  type OfficeCarrier,
  type TrackingTone,
} from "@/lib/office-delivery";

const TONE: Record<TrackingTone, string> = {
  slate: "bg-sunken text-muted",
  violet: "bg-violet-50 text-violet-600",
  blue: "bg-blue-50 text-blue-600",
  green: "bg-emerald-50 text-emerald-600",
  red: "bg-red-50 text-red-600",
};

function Kpi({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface px-4 py-3">
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

type ListStatus = "loading" | "success" | "error";

function CarrierRequestModal({
  delivery,
  carriers,
  carriersStatus,
  carrierError,
  requestError,
  onRetryCarriers,
  onClose,
  onSubmit,
}: {
  delivery: Delivery;
  carriers: OfficeCarrier[];
  carriersStatus: ListStatus;
  carrierError: string | null;
  requestError: string | null;
  onRetryCarriers: () => void;
  onClose: () => void;
  onSubmit: (carrierId: string) => Promise<boolean>;
}) {
  const [carrier, setCarrier] = useState(carriers[0]?.id ?? "");
  const [date, setDate] = useState("");
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    if (!carrier || submitting) return;
    setSubmitting(true);
    try {
      if (await onSubmit(carrier)) onClose();
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={onClose}>
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-md overflow-hidden rounded-2xl bg-surface shadow-pop"
      >
        <div className="flex items-start justify-between gap-2 border-b border-line px-5 py-4">
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
              <Truck size={18} />
            </span>
            <div>
              <h3 className="font-bold text-ink">Заявка перевозчику</h3>
              <div className="text-xs text-muted">
                Документ № {delivery.code} · {delivery.company}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="shrink-0 text-faint hover:text-muted" aria-label="Закрыть">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-4 p-5">
          <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2.5 text-sm text-amber-700">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" />
            <span>Варианты из прототипного справочника. Тарифы, сроки, рейтинг и пригодность не подтверждены.</span>
          </div>

          {carrierError && (
            <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {carrierError} <button onClick={onRetryCarriers} className="font-semibold underline">Повторить</button>
            </div>
          )}

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">Вариант из справочника</span>
            <select
              value={carrier}
              onChange={(event) => setCarrier(event.target.value)}
              disabled={carriersStatus !== "success" || carriers.length === 0 || submitting}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent disabled:opacity-60"
            >
              {carriers.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
            {carriersStatus === "loading" && <span role="status" className="mt-1 block text-xs text-muted">Загружаем варианты…</span>}
            {carriersStatus === "success" && carriers.length === 0 && <span className="mt-1 block text-xs text-muted">Справочник пуст.</span>}
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">Желаемая дата подачи</span>
            <input
              value={date}
              onChange={(event) => setDate(event.target.value)}
              placeholder="напр. 12.06"
              disabled={submitting}
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs font-medium text-muted">Комментарий</span>
            <textarea
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              rows={2}
              placeholder="Адрес, контактное лицо, упаковка…"
              disabled={submitting}
              className="w-full resize-none rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
            />
          </label>

          {requestError && <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{requestError}</div>}
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">
          <button
            onClick={onClose}
            disabled={submitting}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-muted hover:bg-sunken"
          >
            Отмена
          </button>
          <button
            onClick={() => void submit()}
            disabled={!carrier || carriersStatus !== "success" || submitting}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Send size={16} /> {submitting ? "Отправка…" : "Отправить заявку"}
          </button>
        </div>
      </div>
    </div>
  );
}

export function OfficeDelivery({
  deliveries,
  carriers,
  deliveriesStatus,
  deliveriesError,
  carriersStatus,
  carriersError,
  carrierRequestError,
  onRetryDeliveries,
  onRetryCarriers,
  onAssignCarrier,
}: {
  deliveries: Delivery[];
  carriers: OfficeCarrier[];
  deliveriesStatus: ListStatus;
  deliveriesError: string | null;
  carriersStatus: ListStatus;
  carriersError: string | null;
  carrierRequestError: string | null;
  onRetryDeliveries: () => void;
  onRetryCarriers: () => void;
  onAssignCarrier: (id: number, carrierId: string) => Promise<boolean>;
}) {
  const [modalFor, setModalFor] = useState<Delivery | null>(null);
  const summary = summarizeDeliveries(deliveries);
  const hasRowsOrSuccessfulLoad = deliveries.length > 0 || deliveriesStatus === "success";
  const stale = deliveries.length > 0 && deliveriesStatus !== "success";

  return (
    <main className="flex-1 overflow-auto p-6">
      <div>
        <h1 className="text-xl font-bold text-ink">Доставка и трекинг</h1>
        <p className="mt-0.5 text-sm text-muted">
          Документы офиса и только подтверждённые события доставки. Даты операции не показываются как сроки доставки.
        </p>
      </div>

      {deliveriesStatus === "loading" && deliveries.length === 0 && (
        <p role="status" className="mt-4 text-sm text-muted">Загружаем документы…</p>
      )}
      {stale && (
        <p role="status" className="mt-4 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Показаны сохранённые строки; текущий список ещё не подтверждён.
        </p>
      )}
      {deliveriesError && (
        <div role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {deliveriesError} <button onClick={onRetryDeliveries} className="font-semibold underline">Повторить</button>
        </div>
      )}
      {carriersStatus === "loading" && (
        <p role="status" className="mt-3 text-sm text-muted">Загружаем справочник вариантов…</p>
      )}
      {carriersError && (
        <div role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {carriersError} <button onClick={onRetryCarriers} className="font-semibold underline">Повторить справочник</button>
        </div>
      )}
      {hasRowsOrSuccessfulLoad && (
        <div className="mt-3 flex justify-end">
          <button
            onClick={onRetryDeliveries}
            disabled={deliveriesStatus === "loading"}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-muted hover:bg-sunken disabled:opacity-60"
          >
            {deliveriesStatus === "loading" ? "Обновление…" : "Обновить документы"}
          </button>
        </div>
      )}

      {hasRowsOrSuccessfulLoad && (
        <>
          <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
            <Kpi label="Документов" value={String(summary.total)} />
            <Kpi label="В пути по событию" value={String(summary.inTransit)} tone="text-blue-600" />
            <Kpi label="Доставлено по событию" value={String(summary.delivered)} tone="text-emerald-600" />
            <Kpi label="Задержки по событию" value={String(summary.delayed)} tone="text-red-600" />
            <Kpi label="Сумма документов" value={formatByn(summary.totalAmount)} tone="text-ink" />
          </div>
          <p className="mt-3 text-xs text-muted">
            Статус подтверждён для {summary.trackingKnown} из {summary.total} документов; вес указан для {summary.weightKnown} из {summary.total}.
          </p>
        </>
      )}

      {carriersStatus === "success" && carriers.length > 0 && (
        <p className="mt-3 text-xs text-muted">Справочник вариантов прототипный; цены, сроки, рейтинг и условия перевозки не подтверждены.</p>
      )}

      <div className="mt-5 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2.5 font-medium">№</th>
              <th className="px-4 py-2.5 font-medium">Компания</th>
              <th className="px-4 py-2.5 font-medium">Назначение</th>
              <th className="px-4 py-2.5 font-medium">Вес</th>
              <th className="px-4 py-2.5 font-medium">Сумма</th>
              <th className="px-4 py-2.5 font-medium">Статус события</th>
              <th className="px-4 py-2.5 font-medium">Способ / перевозчик из документа</th>
            </tr>
          </thead>
          <tbody>
            {deliveriesStatus === "success" && deliveries.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-muted">Документов нет</td>
              </tr>
            )}
            {deliveries.map((delivery) => {
              const weight = parseWeightKg(delivery.weight);
              return (
                <tr key={delivery.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-3 text-muted">{delivery.code}</td>
                  <td className="px-4 py-3 font-medium text-ink">{delivery.company}</td>
                  <td className="px-4 py-3 text-muted">
                    <span className="inline-flex items-center gap-1">
                      <MapPin size={13} className="text-faint" />
                      {delivery.destination ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted">{weight === null ? "Не указан" : `${formatNumber(weight)} кг`}</td>
                  <td className="px-4 py-3 font-medium text-ink">{formatByn(delivery.amount)}</td>
                  <td className="px-4 py-3"><StageBadge stage={delivery.stage} /></td>
                  <td className="px-4 py-3">
                    {delivery.carrier ? (
                      <span className="inline-flex items-center gap-1.5 text-muted"><Truck size={14} />{delivery.carrier}</span>
                    ) : canRequestCarrier(delivery) ? (
                      carriersStatus === "success" && carriers.length > 0 ? (
                        <button
                          onClick={() => setModalFor(delivery)}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-accent-soft px-2.5 py-1.5 text-xs font-medium text-accent-ink hover:bg-sunken"
                        >
                          <Truck size={14} /> Заявка перевозчику
                        </button>
                      ) : (
                        <span className="text-xs text-muted">Справочник вариантов недоступен</span>
                      )
                    ) : (
                      <span className="text-xs text-muted">Не указано</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {modalFor && (
        <CarrierRequestModal
          delivery={modalFor}
          carriers={carriers}
          carriersStatus={carriersStatus}
          carrierError={carriersError}
          requestError={carrierRequestError}
          onRetryCarriers={onRetryCarriers}
          onClose={() => setModalFor(null)}
          onSubmit={(carrierId) => onAssignCarrier(modalFor.id, carrierId)}
        />
      )}
    </main>
  );
}
