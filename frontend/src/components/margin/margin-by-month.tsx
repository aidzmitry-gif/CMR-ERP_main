"use client";

import { Link2, Package, Target, TrendingUp, Truck, User } from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn, plural } from "@/lib/format";

// demo-данные (бэкенда по экрану пока нет). Валюта — BYN.
// Месяц поставки = ETA рейса (логистика). Себестоимость (landed cost) — из закупок,
// валовая прибыль = выручка − себестоимость.

type ManagerKey = "all" | "orlov" | "petrova" | "sidorov";

type ShipStatus = "transit" | "plan" | "done";

type Ship = {
  id: string;
  sub: string;
  status: ShipStatus;
  mgr: Exclude<ManagerKey, "all"> | "all";
  goods: { name: string; qty: string }[];
  rev: number;
  cost: number;
  gp: number;
};

type MonthCol = {
  key: string;
  title: string;
  /** цвет полосы шапки — из палитры стадий воронки */
  stripe: string;
  /** плановая вместимость месяца (BYN) для расчёта % загрузки */
  capacity: number;
  /** месячная цель по валовой прибыли (BYN) */
  target: number;
  ships: Ship[];
};

// Годовая цель = факт (закрытые янв–май) + план вперёд (июнь+) + «добрать».
const ANNUAL_GOAL = 760_000;
const FACT_PRIOR = 280_000;

const MONTHS: MonthCol[] = [
  {
    key: "jun",
    title: "Июнь",
    stripe: "bg-stage-new",
    capacity: Math.round(186_000 / 0.88),
    target: 70_000,
    ships: [
      {
        id: "TR-0418 · AB 7421-7",
        sub: "прибытие 18.06",
        status: "transit",
        mgr: "sidorov",
        goods: [
          { name: "АКБ 6СТ-190 · Белтранс", qty: "38 шт" },
          { name: "АКБ 6СТ-225 · Минскэлектро", qty: "14 шт" },
        ],
        rev: 61_200,
        cost: 38_400,
        gp: 22_800,
      },
      {
        id: "TR-0421 · AB 9012-3",
        sub: "прибытие 24.06",
        status: "plan",
        mgr: "petrova",
        goods: [{ name: "АКБ промышл. · Нафтан", qty: "24 шт" }],
        rev: 68_200,
        cost: 45_800,
        gp: 22_400,
      },
      {
        id: "TR-0409 · AB 5567-1",
        sub: "доставлено 06.06",
        status: "done",
        mgr: "sidorov",
        goods: [{ name: "АКБ + ЗУ · Белводхоз", qty: "30 шт" }],
        rev: 56_600,
        cost: 38_600,
        gp: 18_000,
      },
    ],
  },
  {
    key: "jul",
    title: "Июль",
    stripe: "bg-indigo-500",
    capacity: Math.round(198_000 / 1.0),
    target: 70_000,
    ships: [
      {
        id: "TR-0430 · план",
        sub: "перезаказ Белтранс ~05.07",
        status: "plan",
        mgr: "sidorov",
        goods: [{ name: "АКБ 6СТ-190 + 2 ЗУ", qty: "42 шт" }],
        rev: 52_000,
        cost: 32_800,
        gp: 19_200,
      },
      {
        id: "TR-0433 · план",
        sub: "Автопарк №7 ~12.07",
        status: "plan",
        mgr: "orlov",
        goods: [{ name: "АКБ годовой объём", qty: "45 шт" }],
        rev: 54_000,
        cost: 34_500,
        gp: 19_500,
      },
      {
        id: "TR-0436 · план",
        sub: "тендер МЧС ~20.07",
        status: "plan",
        mgr: "orlov",
        goods: [{ name: "АКБ для МЧС", qty: "60 шт" }],
        rev: 92_000,
        cost: 59_200,
        gp: 32_800,
      },
    ],
  },
  {
    key: "aug",
    title: "Август",
    stripe: "bg-stage-appr",
    capacity: Math.round(130_000 / 0.54),
    target: 70_000,
    ships: [
      {
        id: "TR-0450 · прогноз",
        sub: "перезаказ Белводхоз ~27.07→08",
        status: "plan",
        mgr: "sidorov",
        goods: [{ name: "АКБ + ЗУ", qty: "30 шт" }],
        rev: 52_400,
        cost: 35_000,
        gp: 17_400,
      },
      {
        id: "TR-0455 · прогноз",
        sub: "Минскэлектро ~02.08",
        status: "plan",
        mgr: "petrova",
        goods: [{ name: "АКБ промышл.", qty: "14 шт" }],
        rev: 38_900,
        cost: 26_400,
        gp: 12_500,
      },
    ],
  },
  {
    key: "sep",
    title: "Сентябрь+",
    stripe: "bg-line-strong",
    capacity: Math.round(92_000 / 0.3),
    target: 270_000,
    ships: [
      {
        id: "прогноз по циклу",
        sub: "формируется из перезаказов",
        status: "plan",
        mgr: "all",
        goods: [{ name: "АКБ (по периодичности клиентов)", qty: "~50 шт" }],
        rev: 92_000,
        cost: 63_600,
        gp: 28_400,
      },
    ],
  },
];

const MANAGERS: { key: ManagerKey; label: string }[] = [
  { key: "all", label: "Все (отдел)" },
  { key: "orlov", label: "Орлов И." },
  { key: "petrova", label: "Петрова А." },
  { key: "sidorov", label: "Сидоров К." },
];

const STATUS: Record<ShipStatus, { label: string; cls: string }> = {
  transit: { label: "в пути", cls: "bg-amber-50 text-amber-600" },
  plan: { label: "план", cls: "bg-blue-50 text-blue-600" },
  done: { label: "доставлено", cls: "bg-emerald-50 text-emerald-600" },
};

type MonthStat = {
  col: MonthCol;
  ships: Ship[];
  rev: number;
  cost: number;
  gp: number;
  count: number;
  margin: number;
  load: number;
};

export function MarginByMonth() {
  const [manager, setManager] = useState<ManagerKey>("all");

  // Пересчёт всех итогов под выбранного менеджера (как в макете): «Все» — показываем
  // все рейсы; иначе только рейсы менеджера (общий прогноз data-mgr="all" скрываем).
  const months: MonthStat[] = useMemo(() => {
    return MONTHS.map((col) => {
      const ships = col.ships.filter((s) => manager === "all" || s.mgr === manager);
      const rev = ships.reduce((sum, s) => sum + s.rev, 0);
      const cost = ships.reduce((sum, s) => sum + s.cost, 0);
      const gp = ships.reduce((sum, s) => sum + s.gp, 0);
      const count = ships.length;
      const margin = rev ? Math.round((gp / rev) * 100) : 0;
      const load = Math.min(100, Math.round((rev / col.capacity) * 100));
      return { col, ships, rev, cost, gp, count, margin, load };
    });
  }, [manager]);

  // Годовая шапка: цель = факт (закрыто, янв–май) + план вперёд + «добрать».
  // Уровень отдела (не зависит от фильтра менеджера) — берём полные планы месяцев.
  const goal = useMemo(() => {
    const planAhead = MONTHS.reduce(
      (sum, col) => sum + col.ships.reduce((s, sh) => s + sh.gp, 0),
      0,
    );
    const gap = Math.max(0, ANNUAL_GOAL - FACT_PRIOR - planAhead);
    const pc = (n: number) => Math.round((n / ANNUAL_GOAL) * 100);
    return {
      planAhead,
      gap,
      factP: pc(FACT_PRIOR),
      planP: pc(planAhead),
      gapP: pc(gap),
    };
  }, []);

  function loadLabel(stat: MonthStat): string {
    if (manager !== "all") {
      return stat.count ? `доля менеджера · ${stat.load}% месяца` : "нет рейсов этого менеджера";
    }
    if (stat.load >= 100) return "загрузка 100% · нужна ещё машина";
    if (stat.load >= 80) return `загрузка ~${stat.load}% · ещё есть место`;
    return `загрузка ~${stat.load}% · добирать сделками`;
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div>
          <h1 className="text-xl font-bold text-ink">План валовой прибыли по месяцам</h1>
          <p className="mt-0.5 text-sm text-muted">
            Какие машины и товары в каком месяце · плановая валовая прибыль и загрузка · BYN ·
            маржа = продажа − landed cost (из закупок)
          </p>
        </div>

        {/* Годовая цель · валовая прибыль — декомпозиция по месяцам */}
        <section className="rounded-2xl border border-line bg-surface p-4 shadow-card">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-bold text-ink">
              <Target size={16} className="text-accent" />
              <span>
                Годовая цель · валовая прибыль{" "}
                <span className="text-[11px] font-semibold text-faint">
                  2026 · декомпозиция по месяцам
                </span>
              </span>
            </div>
            <div className="text-xl font-bold tabular-nums text-ink">{formatByn(ANNUAL_GOAL)}</div>
          </div>

          <div className="my-3 flex h-2.5 overflow-hidden rounded-full bg-sunken">
            <span className="h-full bg-emerald-500" style={{ width: `${goal.factP}%` }} />
            <span className="h-full bg-accent" style={{ width: `${goal.planP}%` }} />
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-1.5 text-xs text-muted">
            <span className="flex items-center gap-1.5">
              <i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-emerald-500" />
              Факт (янв–май): <b className="font-semibold tabular-nums text-ink">{formatByn(FACT_PRIOR)}</b>
              <em className="not-italic text-faint">{goal.factP}%</em>
            </span>
            <span className="flex items-center gap-1.5">
              <i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-accent" />
              План вперёд (июнь+): <b className="font-semibold tabular-nums text-ink">{formatByn(goal.planAhead)}</b>
              <em className="not-italic text-faint">{goal.planP}%</em>
            </span>
            <span className="flex items-center gap-1.5">
              <i className="inline-block h-2.5 w-2.5 rounded-[3px] bg-line-strong" />
              Осталось до годовой цели: <b className="font-semibold tabular-nums text-ink">{formatByn(goal.gap)}</b>
              <em className="not-italic text-faint">{goal.gapP}%</em>
            </span>
          </div>
        </section>

        {/* Фильтр по менеджерам: каждый видит свои цифры */}
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold text-muted">
            <User size={15} /> Менеджер:
          </span>
          <div className="inline-flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
            {MANAGERS.map((m) => (
              <button
                key={m.key}
                onClick={() => setManager(m.key)}
                className={`rounded-lg px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
                  manager === m.key
                    ? "bg-accent-soft text-accent-ink"
                    : "text-muted hover:text-accent-ink"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {/* Сводка по месяцам (KPI-плитки) */}
        <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
          {months.map((stat) => {
            const loadBar =
              stat.load >= 100 ? "bg-amber-500" : stat.load >= 80 ? "bg-emerald-500" : "bg-accent";
            const diff = stat.gp - stat.col.target;
            const contrib = stat.col.target ? Math.round((stat.gp / stat.col.target) * 100) : 0;
            return (
              <div
                key={stat.col.key}
                className="overflow-hidden rounded-2xl bg-surface shadow-card"
              >
                <div className={`h-[3px] w-full ${stat.col.stripe}`} />
                <div className="p-4">
                  <div className="text-[15px] font-bold text-ink">{stat.col.title} 2026</div>
                  <div className="mt-2 text-[11px] text-muted">Валовая прибыль (план)</div>
                  <div className="text-2xl font-bold tabular-nums tracking-tight text-money">
                    {formatByn(stat.gp)}
                  </div>
                  <div className="mt-0.5 text-[11.5px] font-semibold text-money">
                    маржа {stat.margin}% · выручка {formatByn(stat.rev)}
                  </div>
                  <div className="mt-1.5 flex justify-between text-[11.5px] text-muted">
                    <span>Себестоимость {formatByn(stat.cost)}</span>
                    <span>{stat.count} {plural(stat.count, ["машина", "машины", "машин"])}</span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
                    <div className={`h-full rounded-full ${loadBar}`} style={{ width: `${stat.load}%` }} />
                  </div>
                  <div className="mt-1 text-[10.5px] text-faint">{loadLabel(stat)}</div>

                  {/* строка «цель месяца / добрать» (всё) либо «вклад менеджера в цель» */}
                  <div className="mt-2 flex justify-between gap-2 border-t border-dashed border-line pt-2 text-[11px]">
                    {manager === "all" ? (
                      <span>
                        цель {formatByn(stat.col.target)} ·{" "}
                        {diff >= 0 ? (
                          <span className="font-semibold text-money">
                            цель достигнута · +{formatByn(diff)}
                          </span>
                        ) : (
                          <span className="font-semibold text-amber-600">
                            добрать {formatByn(-diff)}
                          </span>
                        )}
                      </span>
                    ) : (
                      <span>
                        вклад в цель:{" "}
                        <b className="font-semibold tabular-nums text-ink">{formatByn(stat.gp)}</b> ({contrib}%)
                      </span>
                    )}
                    <span className="whitespace-nowrap text-faint">
                      {Math.round((stat.col.target / ANNUAL_GOAL) * 100)}% год. цели
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Колонки месяцев с машинами */}
        <div className="thin-scroll flex gap-3.5 overflow-x-auto pb-2.5">
          {months.map((stat) => (
            <div key={stat.col.key} className="flex w-[300px] flex-shrink-0 flex-col gap-3">
              {/* шапка колонки */}
              <div className="overflow-hidden rounded-xl bg-surface shadow-card">
                <div className={`h-1 w-full ${stat.col.stripe}`} />
                <div className="px-3.5 py-2.5">
                  <div className="flex items-center justify-between text-sm font-semibold text-ink">
                    {stat.col.title}
                    <span className="rounded-md bg-sunken px-2 py-0.5 text-[11px] font-semibold text-faint">
                      {stat.count} {plural(stat.count, ["машина", "машины", "машин"])}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-muted">
                    выручка {formatByn(stat.rev)} · с/с {formatByn(stat.cost)}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 text-xs font-semibold text-money">
                    <TrendingUp size={13} /> вал. прибыль {formatByn(stat.gp)} ({stat.margin}%)
                  </div>
                </div>
              </div>

              {/* пусто под менеджером */}
              {stat.ships.length === 0 && (
                <div className="rounded-xl border border-dashed border-line bg-surface px-3.5 py-6 text-center text-xs text-faint">
                  Нет рейсов этого менеджера
                </div>
              )}

              {/* карточки рейсов */}
              {stat.ships.map((ship) => {
                const st = STATUS[ship.status];
                const share = stat.gp ? Math.round((ship.gp / stat.gp) * 100) : 0;
                return (
                  <div key={ship.id} className="rounded-xl bg-surface p-3 shadow-card hover:shadow-pop">
                    <div className="flex items-center gap-2">
                      <span className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-ink">
                        <Truck size={15} />
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-[12.5px] font-semibold text-ink">{ship.id}</div>
                        <div className="text-[11px] text-faint">{ship.sub}</div>
                      </div>
                      <span
                        className={`ml-auto whitespace-nowrap rounded-md px-1.5 py-0.5 text-[9.5px] font-semibold ${st.cls}`}
                      >
                        {st.label}
                      </span>
                    </div>

                    <div className="mt-2.5 space-y-0.5 text-xs">
                      {ship.goods.map((g) => (
                        <div key={g.name} className="flex justify-between gap-2 text-muted">
                          <span className="flex min-w-0 items-center gap-1.5">
                            <Package size={12} className="flex-shrink-0 text-faint" />
                            <span className="truncate">{g.name}</span>
                          </span>
                          <span className="flex-shrink-0 tabular-nums">{g.qty}</span>
                        </div>
                      ))}
                    </div>

                    <div className="mt-2.5 flex border-t border-line pt-2.5 text-xs">
                      <div className="flex-1 text-center">
                        <div className="text-[9.5px] text-faint">Выручка</div>
                        <div className="mt-0.5 font-semibold tabular-nums text-ink">{formatByn(ship.rev)}</div>
                      </div>
                      <div className="flex-1 text-center">
                        <div className="text-[9.5px] text-faint">С/с</div>
                        <div className="mt-0.5 font-semibold tabular-nums text-ink">{formatByn(ship.cost)}</div>
                      </div>
                      <div className="flex-1 text-center">
                        <div className="text-[9.5px] text-faint">Вал. приб.</div>
                        <div className="mt-0.5 font-semibold tabular-nums text-money">{formatByn(ship.gp)}</div>
                      </div>
                    </div>

                    {/* доля машины в прибыли месяца */}
                    <div className="mt-2 flex items-center gap-2 text-[10.5px] text-muted">
                      <span className="whitespace-nowrap">доля в прибыли месяца</span>
                      <span className="h-1 flex-1 overflow-hidden rounded-full bg-sunken">
                        <span className="block h-full rounded-full bg-accent" style={{ width: `${share}%` }} />
                      </span>
                      <b className="whitespace-nowrap font-semibold text-accent-ink">{share}%</b>
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Сноска */}
        <div className="flex gap-2 text-xs text-faint">
          <Link2 size={14} className="mt-0.5 flex-shrink-0" />
          <span>
            Месяц поставки = ETA рейса (из логистики). Себестоимость (landed cost) — из закупок,
            маржа = продажа − с/с. Так РОП/директор видят{" "}
            <b className="font-semibold text-ink">плановую валовую прибыль помесячно</b> и{" "}
            <b className="font-semibold text-ink">загрузку машин</b> заранее, и могут добирать
            сделками недозагруженные месяцы.
          </span>
        </div>
      </div>
    </main>
  );
}
