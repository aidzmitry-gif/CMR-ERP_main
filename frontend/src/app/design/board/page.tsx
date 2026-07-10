import { Card, Badge, Button, type BadgeTone } from "@/components/ui";
import { STAGES, KPIS } from "@/lib/mock-data";
import { STAGE_PROBABILITY } from "@/lib/board";
import {
  Plus, Search, SlidersHorizontal, Clock, LayoutGrid, List,
  Star, MoreHorizontal, User, Calendar, Flag, Phone, Mail, MessageSquare,
} from "lucide-react";

/**
 * ДЕМО (не продакшн): доска сделок на примитивах components/ui + токены Stripe/Notion.
 * Соответствует ЖИВОМУ /crm/deals по составу: поиск, фильтры, «висяки», План/Факт-скорборд,
 * периоды, переключатель вида, все стадии, полные карточки (дни/вероятность/взвешенно).
 * Статика вида (без drag&drop). Реальный экран не тронут. Открыть: /design/board
 */

const fmt = (n: number) => new Intl.NumberFormat("ru-RU").format(n);
const fmtMoney = (n: number) => `${fmt(n)} ₽`;

const priorityTone: Record<string, BadgeTone> = { Высокий: "red", Средний: "amber", Низкий: "slate" };
const PERIODS = ["День", "Неделя", "Месяц", "Квартал", "Год"];
const PRIORITIES = ["Все", "Высокий", "Средний", "Низкий"];

// тон KPI-скорборда
const kpiTone: Record<string, string> = {
  blue: "#2563EB", indigo: "#635BFF", green: "#0F9D58", cyan: "#0E9384", slate: "#6B6F76",
};

export default function BoardDemoPage() {
  return (
    <main className="mx-auto max-w-[1440px] space-y-0 p-6">
      <p className="mb-3 text-[11px] font-semibold uppercase tracking-wide text-faint">
        Демо · доска сделок (полная, как живой /crm/deals)
      </p>

      {/* ТУЛБАР: поиск + фильтры + висяки + создать */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[220px] max-w-sm flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input
            placeholder="Поиск сделок..."
            className="w-full rounded-[10px] border border-line-strong bg-surface py-2 pl-9 pr-3 text-sm outline-none placeholder:text-faint focus:border-accent"
          />
        </div>
        <Button variant="secondary" size="md" icon={<SlidersHorizontal size={16} />}>
          Фильтры <Badge tone="accent" className="ml-1">Высокий</Badge>
        </Button>
        <Button variant="secondary" size="md" icon={<Clock size={16} />}>Только висяки</Button>
        <Button variant="primary" icon={<Plus size={16} />} className="ml-auto">Создать сделку</Button>
      </div>

      {/* Фильтр по приоритету */}
      <div className="mt-3 flex items-center gap-2">
        <span className="text-sm text-muted">Приоритет:</span>
        {PRIORITIES.map((p, i) => (
          <button
            key={p}
            className={`rounded-lg px-3 py-1 text-sm font-medium ${
              i === 1 ? "bg-accent-soft text-accent-ink" : "bg-surface text-muted ring-1 ring-line-strong hover:bg-sunken"
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* ПЛАН / ФАКТ — скорборд */}
      <section className="mt-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">План / Факт</h2>
          <div className="flex items-center gap-0.5 rounded-[10px] border border-line-strong bg-surface p-0.5">
            {PERIODS.map((p, i) => (
              <button
                key={p}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${
                  i === 0 ? "bg-accent-soft text-accent-ink" : "text-muted hover:text-ink"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
          {KPIS.map((k) => (
            <Card key={k.id} className="p-4">
              <div className="flex items-start justify-between">
                <span className="text-[12px] font-medium leading-tight text-muted">{k.label}</span>
                <span className="size-2 flex-shrink-0 rounded-full" style={{ background: kpiTone[k.tone] }} />
              </div>
              <div className="mt-2 flex items-baseline gap-1.5">
                <span className="text-xl font-bold tabular-nums tracking-tight">
                  {k.money ? fmt(k.value) : k.value}
                </span>
                <span className="text-xs tabular-nums text-faint">/ {k.money ? fmt(k.target) : k.target}</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-[#EEEEF1]">
                <div className="h-full rounded-full" style={{ width: `${k.percent}%`, background: kpiTone[k.tone] }} />
              </div>
              <div className="mt-1.5 flex items-center justify-between">
                <span className="text-[11px] font-semibold tabular-nums" style={{ color: kpiTone[k.tone] }}>{k.percent}%</span>
                <button className="text-[11px] font-semibold text-accent-ink hover:underline">+ записать</button>
              </div>
            </Card>
          ))}
        </div>
      </section>

      {/* Переключатель вида */}
      <div className="mt-5 flex items-center justify-end gap-2">
        <div className="flex items-center gap-0.5 rounded-[10px] border border-line-strong bg-surface p-0.5">
          <button className="rounded-md bg-accent-soft p-1.5 text-accent-ink" title="Канбан"><LayoutGrid size={16} /></button>
          <button className="rounded-md p-1.5 text-faint hover:text-muted" title="Список"><List size={16} /></button>
        </div>
      </div>

      {/* ДОСКА — все стадии */}
      <div className="mt-3 flex gap-4 overflow-x-auto pb-2">
        {STAGES.map((stage) => {
          const weightedSum = stage.deals.reduce(
            (acc, d) => acc + Math.round(d.amount * ((STAGE_PROBABILITY[stage.id] ?? 0) / 100)),
            0,
          );
          return (
            <div key={stage.id} className="w-[300px] flex-shrink-0">
              {/* шапка колонки */}
              <Card className="overflow-hidden">
                <div className="h-1" style={{ background: stage.color }} />
                <div className="px-3.5 py-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-bold">{stage.title}</span>
                    <span className="text-[11px] font-semibold tabular-nums text-muted">{stage.count}</span>
                  </div>
                  <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums">
                    <span className="text-muted">{fmt(stage.sum)} ₽</span>
                    {weightedSum > 0 && (
                      <span className="font-semibold text-accent-ink">≈ {fmt(weightedSum)} ₽</span>
                    )}
                  </div>
                </div>
              </Card>

              {/* карточки сделок */}
              <div className="mt-3 flex flex-col gap-3">
                {stage.deals.map((d) => {
                  const prob = STAGE_PROBABILITY[stage.id] ?? 0;
                  const weighted = Math.round(d.amount * (prob / 100));
                  return (
                    <Card key={d.id} className="cursor-pointer p-3.5 transition-shadow hover:shadow-pop">
                      {/* верх: № + приоритет + дни + звезда */}
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-muted">№ {d.number}</span>
                        <div className="flex items-center gap-1.5">
                          <Badge tone={priorityTone[d.priority] ?? "slate"}>{d.priority}</Badge>
                          <Star size={14} className={d.starred ? "fill-[#F59E0B] text-[#F59E0B]" : "text-[#CBD5E1]"} />
                          <MoreHorizontal size={15} className="text-faint" />
                        </div>
                      </div>

                      <div className="mt-2 font-semibold">{d.company}</div>
                      <div className="text-xs text-muted">{d.description}</div>

                      {/* сумма + вероятность·взвешенно */}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="font-semibold tabular-nums">{fmtMoney(d.amount)}</span>
                        {prob > 0 && (
                          <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-accent-ink">
                            {prob}% · ≈ {fmtMoney(weighted)}
                          </span>
                        )}
                      </div>

                      {/* todo-блок или след.шаг */}
                      {d.todo ? (
                        <div className="mt-2 space-y-1 rounded-lg bg-sunken p-2.5 text-xs text-muted">
                          <div className="font-medium text-ink">Что нужно сделать:</div>
                          <div>{d.todo}</div>
                          <div className="flex justify-between"><span>Дата действия:</span><span className="text-ink">{d.actionDate}</span></div>
                          <div className="pt-0.5 text-ink">Номенклатура: {d.itemsLabel}, {d.itemsCount} поз.</div>
                        </div>
                      ) : (
                        <div className="mt-2 text-xs text-muted">
                          След. шаг: <span className="text-ink">{d.nextStep}</span>
                        </div>
                      )}

                      {/* владелец + дата */}
                      <div className="mt-2 flex items-center justify-between text-xs text-muted">
                        <span className="inline-flex items-center gap-1"><User size={13} /> {d.owner}</span>
                        {d.date && <span className="inline-flex items-center gap-1 tabular-nums"><Calendar size={12} /> {d.date}</span>}
                      </div>

                      {/* приоритет («Фокус» убран по решению оператора) */}
                      <div className="mt-2.5 flex gap-2">
                        <span className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line-strong py-1.5 text-xs font-medium text-muted">
                          <Flag size={13} className="text-[#F59E0B]" /> Приоритет
                        </span>
                      </div>

                      {/* каналы связи */}
                      <div className="mt-2.5 flex items-center gap-2 border-t border-line pt-2.5 text-faint">
                        <Phone size={14} /><Mail size={14} /><MessageSquare size={14} />
                        <span className="ml-auto text-[11px]">каналы связи</span>
                      </div>
                    </Card>
                  );
                })}
                <button className="flex items-center justify-center gap-1.5 rounded-xl border border-dashed border-line-strong py-2.5 text-xs font-medium text-faint transition-colors hover:bg-surface hover:text-muted">
                  <Plus className="size-3.5" /> Добавить сделку
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}
