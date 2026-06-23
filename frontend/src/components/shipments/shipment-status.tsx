"use client";

import {
  Building2,
  CheckCircle2,
  Info,
  Link2,
  MapPin,
  Package,
  Truck,
  User,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn, formatNumber } from "@/lib/format";

// demo-данные (бэкенда по экрану пока нет). Валюта — BYN, формат «280 000 BYN».
// Источник истины по статусу рейса — логистика; остальные роли читают read-only.

type StepState = "done" | "cur" | "future";

type TimelineStep = {
  title: string;
  date: string;
  state: StepState;
};

type GoodsRow = {
  name: string;
  forCustomer: string; // «для кого» — видят продавец и директор
  deal: string; // № сделки — видят все роли
  qty: string;
};

type InternalRole = "sales" | "buyer" | "dir";
type ClientVis = "full" | "short" | "eta" | "hide";

const SHIPMENT = {
  trip: "TR-2026-0418",
  vehicle: "AB 7421-7",
  statusLabel: "В пути до склада",
  route: "Минский склад поставщика → склад Гомель → клиенты",
  driver: "Кравцов А.",
  eta: "18 июня, ~14:00",
  dealsCount: 3,
  positions: "64 АКБ + ЗУ",
  weightKg: 1280,
  nowLocation: "трасса М5, 120 км до склада",
  supplier: "ТД «АКБ-Импорт»",
  supplierUnp: "19283746",
  buyer: "Романюк Д.",
  landedCost: 38400,
  revenue: 61200,
  grossProfit: 22800,
  grossProfitPct: 37,
} as const;

const TIMELINE: TimelineStep[] = [
  { title: "Заказано у поставщика", date: "10.06", state: "done" },
  { title: "Отгружено поставщиком", date: "14.06", state: "done" },
  { title: "В пути до нашего склада", date: "ETA 16.06", state: "cur" },
  { title: "На нашем складе · комплектация", date: "~16–17.06", state: "future" },
  { title: "Доставка клиенту (в пути)", date: "~18.06", state: "future" },
  { title: "Доставлено клиенту", date: "~18.06", state: "future" },
];

const GOODS: GoodsRow[] = [
  { name: "АКБ 6СТ-190 (Зубр)", forCustomer: "ОАО «Белтранс»", deal: "CRM-1029", qty: "38 шт" },
  { name: "АКБ 6СТ-225", forCustomer: "УП «Минскэлектро»", deal: "CRM-0998", qty: "14 шт" },
  { name: "ЗУ + тестеры", forCustomer: "Автопарк №7", deal: "CRM-1024", qty: "12 шт" },
];

const ROLE_NOTE: Record<InternalRole, string> = {
  sales:
    "Продавец видит, кому и по какой сделке идёт товар, выручку и маржу. Поставщик и себестоимость скрыты.",
  buyer:
    "Закупщик видит поставщика и себестоимость, товары и номера сделок — но НЕ видит, какому клиенту они идут.",
  dir: "Директор видит всё: поставщика, себестоимость, выручку, маржу и клиентов.",
};

const ROLE_TABS: { key: InternalRole; label: string }[] = [
  { key: "sales", label: "Продавец" },
  { key: "buyer", label: "Закупщик" },
  { key: "dir", label: "Директор" },
];

const CLIENT_VIS_TABS: { key: ClientVis; label: string }[] = [
  { key: "full", label: "Полный" },
  { key: "short", label: "Сокращённый" },
  { key: "eta", label: "Только дата" },
  { key: "hide", label: "Скрыть" },
];

const CLIENT_STATUS_TEXT: Record<"full" | "short", string> = {
  full: "В пути до склада → к вам",
  short: "В обработке",
};

function nodeClasses(state: StepState): string {
  if (state === "done") return "bg-emerald-500 text-white";
  if (state === "cur")
    return "bg-amber-500 text-white ring-4 ring-amber-500/20";
  return "bg-sunken text-faint";
}

function KeyValue({
  label,
  children,
  money,
}: {
  label: string;
  children: React.ReactNode;
  money?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className={money ? "font-semibold text-money tabular-nums" : "text-ink"}>
        {children}
      </span>
    </div>
  );
}

export function ShipmentStatus() {
  const [role, setRole] = useState<InternalRole>("sales");
  const [clientVis, setClientVis] = useState<ClientVis>("full");

  const showFor = role === "sales" || role === "dir";
  const showCost = role === "buyer" || role === "dir";
  const showMargin = role === "sales" || role === "dir";

  const doneCount = useMemo(
    () => TIMELINE.filter((s) => s.state === "done").length,
    [],
  );
  const progressPct = Math.round((doneCount / (TIMELINE.length - 1)) * 100);

  const showClientStatus = clientVis === "full" || clientVis === "short";
  const showClientEta = clientVis !== "hide";

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок экрана */}
        <div>
          <h1 className="text-xl font-bold text-ink">Статус отгрузки — сквозной</h1>
          <p className="mt-0.5 text-sm text-muted">
            Весь путь: поставщик → наш склад → клиент · один источник истины (логистика) · все
            видят одно и то же
          </p>
        </div>

        {/* Пояснение */}
        <div className="flex items-start gap-2.5 rounded-2xl bg-surface p-3.5 text-[12.5px] text-muted shadow-card">
          <Info size={16} className="mt-0.5 shrink-0 text-accent" />
          <span>
            Один статус рейса виден <b className="font-semibold text-ink">менеджеру, закупщику,
            директору</b> и <b className="font-semibold text-ink">клиенту в личном кабинете</b>.
            Меняет его только логистика — остальные читают. Клиент видит «свою» часть (без
            поставщика и себестоимости).
          </span>
        </div>

        {/* KPI / скорборд рейса */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] uppercase tracking-wide text-faint">Сделок в рейсе</div>
            <div className="mt-1 text-lg font-bold tabular-nums text-ink">
              {SHIPMENT.dealsCount}
            </div>
          </div>
          <div className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] uppercase tracking-wide text-faint">Позиций</div>
            <div className="mt-1 text-lg font-bold text-ink">{SHIPMENT.positions}</div>
          </div>
          <div className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] uppercase tracking-wide text-faint">Вес</div>
            <div className="mt-1 text-lg font-bold tabular-nums text-ink">
              {formatNumber(SHIPMENT.weightKg)} кг
            </div>
          </div>
          <div className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] uppercase tracking-wide text-faint">Прибытие (ETA)</div>
            <div className="mt-1 text-lg font-bold text-accent-ink">{SHIPMENT.eta}</div>
          </div>
          <div className="rounded-2xl bg-surface p-4 shadow-card">
            <div className="text-[11px] uppercase tracking-wide text-faint">Готовность пути</div>
            <div className="mt-1 text-lg font-bold tabular-nums text-ink">{progressPct}%</div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-sunken">
              <div
                className="h-full rounded-full bg-amber-500"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Шапка рейса */}
        <div className="rounded-2xl bg-surface p-4 shadow-card">
          <div className="flex flex-wrap items-center gap-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-accent-soft text-accent-ink">
              <Truck size={22} />
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-base font-bold text-ink">
                  Рейс № {SHIPMENT.trip} · авто {SHIPMENT.vehicle}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-600">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                  {SHIPMENT.statusLabel}
                </span>
              </div>
              <div className="mt-0.5 text-[12.5px] text-muted">
                Маршрут: {SHIPMENT.route} · водитель {SHIPMENT.driver}
              </div>
            </div>
            <div className="ml-auto text-right">
              <div className="text-[11px] text-muted">Прибытие к клиенту (ETA)</div>
              <div className="text-lg font-bold text-accent-ink">{SHIPMENT.eta}</div>
            </div>
          </div>
          <div className="mt-3.5 flex flex-wrap gap-x-6 gap-y-2 border-t border-line pt-3.5 text-[12.5px]">
            <span>
              <span className="text-muted">Сделок в рейсе: </span>
              <b className="font-semibold text-ink">{SHIPMENT.dealsCount}</b>
            </span>
            <span>
              <span className="text-muted">Позиций: </span>
              <b className="font-semibold text-ink">{SHIPMENT.positions}</b>
            </span>
            <span>
              <span className="text-muted">Вес: </span>
              <b className="font-semibold tabular-nums text-ink">
                {formatNumber(SHIPMENT.weightKg)} кг
              </b>
            </span>
            <span>
              <span className="text-muted">Сейчас: </span>
              <b className="font-semibold text-ink">{SHIPMENT.nowLocation}</b>
            </span>
          </div>
        </div>

        {/* Таймлайн полного пути */}
        <div className="rounded-2xl bg-surface p-4 pt-8 shadow-card">
          <div className="flex items-start">
            {TIMELINE.map((step, i) => (
              <div key={step.title} className="relative min-w-0 flex-1 text-center">
                {/* линия к следующему шагу */}
                {i < TIMELINE.length - 1 && (
                  <span
                    className={`absolute left-1/2 top-3.5 -z-0 h-[3px] w-full ${
                      step.state === "done" ? "bg-emerald-500" : "bg-sunken"
                    }`}
                  />
                )}
                {step.state === "cur" && (
                  <span className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-amber-500 px-2 py-0.5 text-[10px] font-bold text-white">
                    сейчас здесь
                  </span>
                )}
                <span
                  className={`relative z-10 mx-auto flex h-7 w-7 items-center justify-center rounded-full text-[13px] ${nodeClasses(
                    step.state,
                  )}`}
                >
                  {step.state === "done" ? (
                    <CheckCircle2 size={16} />
                  ) : step.state === "cur" ? (
                    <Truck size={14} />
                  ) : null}
                </span>
                <div
                  className={`mt-2 px-1 text-[11.5px] font-semibold leading-tight ${
                    step.state === "future" ? "text-faint" : "text-ink"
                  }`}
                >
                  {step.title}
                </div>
                <div
                  className={`mt-1 text-[10.5px] ${
                    step.state === "cur" ? "font-bold text-amber-600" : "text-muted"
                  }`}
                >
                  {step.date}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Две панели: внутренний вид vs кабинет клиента */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* ── Внутренний вид ── */}
          <section className="overflow-hidden rounded-2xl bg-surface shadow-card">
            <header className="flex flex-wrap items-center gap-2 border-b border-line bg-blue-50 px-4 py-3 text-[13.5px] font-bold text-blue-600">
              <Building2 size={16} /> Внутренний вид
              <div className="ml-auto flex flex-wrap gap-1">
                {ROLE_TABS.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    onClick={() => setRole(t.key)}
                    className={`rounded-full px-3 py-1 text-[11.5px] font-semibold transition-colors ${
                      role === t.key
                        ? "bg-accent text-white"
                        : "bg-surface text-muted hover:text-accent-ink"
                    }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </header>
            <div className="p-4">
              {showCost && (
                <>
                  <KeyValue label="Поставщик">
                    <b className="font-semibold text-ink">{SHIPMENT.supplier}</b>{" "}
                    <span className="text-muted">(УНП {SHIPMENT.supplierUnp})</span>
                  </KeyValue>
                  <KeyValue label="Закупщик">{SHIPMENT.buyer}</KeyValue>
                  <KeyValue label="Себестоимость (landed)" money>
                    {formatByn(SHIPMENT.landedCost)}
                  </KeyValue>
                </>
              )}
              {showMargin && (
                <>
                  <KeyValue label="Выручка по рейсу" money>
                    {formatByn(SHIPMENT.revenue)}
                  </KeyValue>
                  <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
                    <span className="text-muted">Валовая прибыль</span>
                    <span className="font-semibold text-emerald-600 tabular-nums">
                      {formatByn(SHIPMENT.grossProfit)} · {SHIPMENT.grossProfitPct}%
                    </span>
                  </div>
                </>
              )}

              <div className="mb-1.5 mt-3 text-[11px] font-semibold uppercase tracking-wide text-faint">
                Товары в машине
              </div>
              <div className="text-[13px]">
                {GOODS.map((g) => (
                  <div
                    key={g.deal}
                    className="flex items-center justify-between gap-3 border-t border-line py-1.5 first:border-t-0"
                  >
                    <div className="min-w-0">
                      <div className="text-ink">{g.name}</div>
                      <div className="text-[11px] text-faint">
                        {showFor && <span>для {g.forCustomer} · </span>}
                        {g.deal}
                      </div>
                    </div>
                    <div className="shrink-0 tabular-nums text-muted">{g.qty}</div>
                  </div>
                ))}
              </div>

              <div className="mt-3 rounded-xl bg-sunken px-3 py-2 text-[11.5px] leading-relaxed text-faint">
                {ROLE_NOTE[role]}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {[
                  "логистика (меняет статус)",
                  "продажи",
                  "закупки",
                  "директор",
                ].map((who) => (
                  <span
                    key={who}
                    className="rounded-lg bg-sunken px-2.5 py-1 text-[11px] text-muted"
                  >
                    {who}
                  </span>
                ))}
              </div>
            </div>
          </section>

          {/* ── Кабинет клиента ── */}
          <section className="overflow-hidden rounded-2xl bg-surface shadow-card">
            <header className="flex flex-wrap items-center gap-2 border-b border-line bg-emerald-50 px-4 py-3 text-[13.5px] font-bold text-emerald-600">
              <User size={16} /> Кабинет клиента
              <span className="ml-auto text-[11px] font-medium text-faint">ОАО «Белтранс»</span>
            </header>
            <div className="p-4">
              {/* Настройка видимости статуса клиенту */}
              <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-dashed border-line pb-3">
                <span className="text-[11.5px] font-semibold text-muted">
                  Видимость статуса клиенту:
                </span>
                <div className="flex flex-wrap gap-1">
                  {CLIENT_VIS_TABS.map((t) => (
                    <button
                      key={t.key}
                      type="button"
                      onClick={() => setClientVis(t.key)}
                      className={`rounded-full px-3 py-1 text-[11.5px] font-semibold transition-colors ${
                        clientVis === t.key
                          ? "bg-accent text-white"
                          : "bg-surface text-muted hover:text-accent-ink"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>

              <KeyValue label="Ваш заказ">
                <b className="font-semibold text-ink">№ CRM-1029</b>
              </KeyValue>
              {showClientStatus && (
                <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
                  <span className="text-muted">Статус</span>
                  <span className="font-semibold text-amber-600">
                    {CLIENT_STATUS_TEXT[clientVis === "full" ? "full" : "short"]}
                  </span>
                </div>
              )}
              {showClientEta && (
                <div className="flex items-center justify-between gap-3 py-1.5 text-sm">
                  <span className="text-muted">Ожидаемая доставка</span>
                  <span className="font-semibold text-accent-ink">{SHIPMENT.eta}</span>
                </div>
              )}

              <div className="mb-1.5 mt-3 text-[11px] font-semibold uppercase tracking-wide text-faint">
                Ваши товары
              </div>
              <div className="text-[13px]">
                <div className="flex items-center justify-between gap-3 py-1.5">
                  <div className="text-ink">АКБ 6СТ-190 (Зубр)</div>
                  <div className="shrink-0 tabular-nums text-muted">38 шт</div>
                </div>
              </div>

              <div className="mt-2.5 flex h-28 items-center justify-center gap-2 rounded-xl bg-sunken text-[12px] text-faint">
                <MapPin size={16} /> карта маршрута
              </div>
              <p className="mt-2 text-[11.5px] leading-relaxed text-faint">
                Клиент видит только свою часть заказа и статус. Внутренние данные в кабинет не
                выводятся вовсе. Объём статуса настраивается переключателем выше.
              </p>
            </div>
          </section>
        </div>

        {/* Источник истины */}
        <div className="flex items-start gap-2.5 rounded-2xl bg-surface p-3.5 text-[12px] text-faint shadow-card">
          <Link2 size={16} className="mt-0.5 shrink-0 text-muted" />
          <span>
            <b className="font-semibold text-ink">Источник истины — логистика</b> (рейс/ETA/этап).
            Sales-карточка и кабинет клиента подписаны на событие{" "}
            <b className="font-semibold text-ink">shipment.status.changed</b> и показывают линию
            read-only. Себестоимость/поставщик — из закупок, клиенту не видны.
          </span>
        </div>

        {/* Сводка по позициям рейса (итоги) */}
        <section className="overflow-hidden rounded-2xl bg-surface shadow-card">
          <header className="flex items-center gap-2 border-b border-line px-4 py-3 text-[13.5px] font-bold text-ink">
            <Package size={16} /> Позиции рейса по сделкам
          </header>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                <tr>
                  <th className="px-4 py-2.5 font-semibold">Товар</th>
                  {showFor && <th className="px-4 py-2.5 font-semibold">Клиент</th>}
                  <th className="px-4 py-2.5 font-semibold">Сделка</th>
                  <th className="px-4 py-2.5 text-right font-semibold">Количество</th>
                </tr>
              </thead>
              <tbody>
                {GOODS.map((g) => (
                  <tr key={g.deal} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5 font-medium text-ink">{g.name}</td>
                    {showFor && <td className="px-4 py-2.5 text-muted">{g.forCustomer}</td>}
                    <td className="px-4 py-2.5 text-muted">{g.deal}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-muted">{g.qty}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-sunken/60">
                  <td
                    className="px-4 py-2.5 text-[12px] font-semibold text-muted"
                    colSpan={showFor ? 3 : 2}
                  >
                    Итого позиций в рейсе
                  </td>
                  <td className="px-4 py-2.5 text-right text-[12px] font-bold tabular-nums text-ink">
                    {SHIPMENT.positions}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
