"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, RefreshCw } from "lucide-react";
import { RopTabs } from "@/components/rop/rop-tabs";
import { Avatar, Bar, Card, Tag } from "@/components/rop/ui";
import { readRopDeals, ropSnapshot, ropStepTime, type RopDeal } from "@/lib/rop-overview";

type ReadState = { status: "loading" } | { status: "error"; message: string } |
  { status: "ready"; deals: RopDeal[]; at: Date };
type Filter = "all" | "overdue" | "missingStep" | "lateClose";
const dateTime = new Intl.DateTimeFormat("ru-RU", { timeZone: "Europe/Minsk", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const button = "inline-flex items-center justify-center gap-2 rounded-xl border border-line bg-surface px-3 py-2 text-sm font-semibold text-ink hover:bg-sunken disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

export function RopOverview() {
  const [read, setRead] = useState<ReadState>({ status: "loading" });
  const [filter, setFilter] = useState<Filter>("all");
  const [limit, setLimit] = useState(8);
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    const version = ++sequence.current;
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setRead({ status: "loading" });
    try {
      const response = await fetch("/api/sales/deals", { cache: "no-store", signal: request.signal });
      if (!response.ok) {
        throw new Error(response.status === 401 ? "Сессия истекла. Войдите в ERP снова." :
          response.status === 403 ? "Нет доступа к обзору сделок. Обратитесь к администратору." :
            "Не удалось загрузить сделки. Повторите запрос.");
      }
      const deals = readRopDeals(await response.json());
      if (version === sequence.current && !request.signal.aborted) setRead({ status: "ready", deals, at: new Date() });
    } catch (error) {
      if (version !== sequence.current || request.signal.aborted) return;
      const message = error instanceof Error && /^(Сессия|Нет доступа|Не удалось)/.test(error.message)
        ? error.message : "Не удалось прочитать данные сделок. Повторите запрос.";
      setRead({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => { if (!cancelled) void load(); });
    return () => { cancelled = true; controller.current?.abort(); };
  }, [load]);

  const snapshot = useMemo(() => read.status === "ready" ? ropSnapshot(read.deals, read.at) : null, [read]);
  const focus = snapshot?.attention.filter(item => filter === "all" || item[filter]) ?? [];

  return (
    <div className="mx-auto w-full max-w-[1220px] space-y-5">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wider text-accent">Рабочее место руководителя продаж</p>
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-ink">Обзор РОП</h1>
          <p className="mt-1 text-sm text-muted">Текущая воронка, команда и ближайшие действия по доступным вам сделкам.</p>
        </div>
        <button type="button" onClick={() => void load()} disabled={read.status === "loading"} className={`${button} shrink-0 self-start`}>
          <RefreshCw size={15} aria-hidden="true" /> Обновить
        </button>
      </header>

      <RopTabs active="overview" />

      {read.status === "loading" && <div role="status" className="rounded-2xl border border-line bg-surface p-6 text-sm text-muted">Загружаем доступные сделки…</div>}
      {read.status === "error" && <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">{read.message}</div>}
      {read.status === "ready" && snapshot && <>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span className="inline-flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />Данные ERP · снимок на {dateTime.format(read.at)} · Минск</span>
          <span>Все даты создания · в пределах ваших прав</span>
        </div>

        {snapshot.total === 0 ? <Card>
          <h2 className="font-semibold text-ink">В доступной области сделок пока нет</h2>
          <p className="mt-2 text-sm text-muted">Обзор показывает только сделки, которые разрешено видеть вашей учётной записи.</p>
          <Link href="/crm/deals" className="mt-4 inline-flex items-center gap-2 text-sm font-semibold text-accent">Открыть сделки <ArrowRight size={15} aria-hidden="true" /></Link>
        </Card> : <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[
              { label: "В работе", value: snapshot.open, note: "Включая условные отказы", tone: "text-ink" },
              { label: "Требуют внимания", value: snapshot.attention.length, note: "Сделок с незавершённым действием", tone: snapshot.attention.length ? "text-amber-700" : "text-ink" },
              { label: "Шаг просрочен", value: snapshot.overdue, note: "Срок следующего действия прошёл", tone: snapshot.overdue ? "text-red-600" : "text-ink" },
              { label: "Успешные сделки", value: snapshot.won, note: "Текущая стадия «Успех» · все даты", tone: "text-emerald-700" },
            ].map(kpi => <Card key={kpi.label} className="!p-4">
              <p className="text-xs font-medium text-muted">{kpi.label}</p>
              <p className={`mt-2 text-3xl font-bold tabular-nums ${kpi.tone}`}>{kpi.value}</p>
              <p className="mt-2 text-xs leading-relaxed text-muted">{kpi.note}</p>
            </Card>)}
          </div>

          <Card className="!p-4 sm:!p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div><h2 className="text-base font-semibold text-ink">На что обратить внимание</h2>
                <p className="mt-1 text-xs text-muted">Сначала просроченные действия. Откройте карточку, чтобы уточнить шаг и срок.</p></div>
              <Tag tone="amber">{snapshot.attention.length} из {snapshot.total} сделок</Tag>
            </div>
            <div role="group" aria-label="Фильтр внимания" className="mt-4 flex flex-wrap gap-2">
              {([
                ["all", "Все", snapshot.attention.length], ["overdue", "Просрочен шаг", snapshot.overdue],
                ["missingStep", "Нет шага или срока", snapshot.missingStep], ["lateClose", "Прошла дата закрытия", snapshot.lateClose],
              ] as const).map(([id, label, count]) => <button type="button" key={id} aria-pressed={filter === id}
                onClick={() => { setFilter(id); setLimit(8); }}
                className={`rounded-lg border px-3 py-2 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${filter === id ? "border-accent bg-accent-soft text-accent-ink" : "border-line text-muted hover:bg-sunken"}`}>
                {label} <span className="ml-1 tabular-nums">{count}</span>
              </button>)}
            </div>
            <ul className="mt-3 divide-y divide-line">
              {focus.slice(0, limit).map(item => {
                const nextTime = ropStepTime(item.deal.next_step_at);
                return <li key={item.deal.id} className="py-4 first:pt-2 last:pb-0">
                  <Link href={`/crm/deals/${item.deal.id}`} className="group flex min-w-0 items-start justify-between gap-3 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
                    <div className="min-w-0">
                      <p className="break-words text-sm font-semibold text-ink group-hover:text-accent">{item.deal.title || item.deal.number || `Сделка #${item.deal.id}`}</p>
                      <p className="mt-1 break-words text-xs text-muted">{item.deal.counterparty || "Клиент не указан"} · {item.deal.number || `#${item.deal.id}`}</p>
                      <div className="mt-2 flex flex-wrap gap-1.5">{item.reasons.map(reason => <Tag key={reason} tone={reason === "Следующий шаг просрочен" ? "red" : "amber"}>{reason}</Tag>)}</div>
                      <p className="mt-2 break-words text-xs leading-relaxed text-muted">{item.deal.next_step?.trim() || "Следующее действие не указано"}
                        {nextTime !== null && <> · {dateTime.format(new Date(nextTime))} (Минск)</>}</p>
                    </div>
                    <ArrowRight size={17} className="mt-1 shrink-0 text-faint group-hover:text-accent" aria-hidden="true" />
                  </Link>
                </li>;
              })}
            </ul>
            {focus.length === 0 && <p className="mt-4 text-sm text-muted">В этом фильтре сделок нет.</p>}
            {focus.length > limit && <button type="button" className={`${button} mt-4`} onClick={() => setLimit(value => value + 8)}>Показать ещё · осталось {focus.length - limit}</button>}
            <p className="mt-4 text-xs text-muted">Одна сделка может иметь несколько причин внимания; в общем итоге она учитывается один раз.</p>
          </Card>

          <div className="grid items-start gap-4 lg:grid-cols-2">
            <Card>
              <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 className="font-semibold text-ink">Воронка сейчас</h2><span className="text-xs text-muted">{snapshot.total} сделок · все этапы</span></div>
              <div className="mt-4 space-y-3">
                {snapshot.stages.map(stage => <div key={stage.id}>
                  <div className="flex items-start justify-between gap-3 text-xs"><span className="min-w-0 break-words text-muted">{stage.title}</span><span className="font-semibold tabular-nums text-ink">{stage.count}</span></div>
                  <div className="mt-1.5"><Bar percent={stage.count / Math.max(1, ...snapshot.stages.map(row => row.count)) * 100} tone={stage.id === "won" ? "green" : stage.id === "lost" ? "slate" : "blue"} /></div>
                </div>)}
              </div>
              <p className="mt-4 text-xs leading-relaxed text-muted">Распределение по текущим стадиям. Оно не показывает переходы или конверсию за период.</p>
            </Card>
            <Card>
              <h2 className="font-semibold text-ink">Нагрузка команды</h2>
              <p className="mt-1 text-xs text-muted">Только сотрудники, чьи сделки доступны вам.</p>
              <ul className="mt-2 divide-y divide-line">
                {snapshot.team.map(person => <li key={person.ownerId ?? "unassigned"} className="py-4 last:pb-0">
                  <div className="flex min-w-0 items-center gap-2"><Avatar name={person.ownerId === null ? "?" : person.name} /><div className="min-w-0">
                    <p className="break-words text-sm font-medium text-ink">{person.ownerId === null ? "Без ответственного" : person.name}</p>
                    <p className="text-xs text-muted">{person.ownerId === null ? "Ответственный не назначен" : `ID сотрудника: ${person.ownerId}`}{person.ownerId !== null && person.labels.size > 1 ? " · подписи в сделках различаются" : ""}</p>
                  </div></div>
                  <dl className="mt-3 grid grid-cols-3 gap-2 text-xs"><div><dt className="text-muted">В работе</dt><dd className="mt-1 font-semibold tabular-nums text-ink">{person.open}</dd></div><div><dt className="text-muted">Внимание</dt><dd className="mt-1 font-semibold tabular-nums text-amber-700">{person.attention}</dd></div><div><dt className="text-muted">Всего</dt><dd className="mt-1 font-semibold tabular-nums text-ink">{person.total}</dd></div></dl>
                </li>)}
              </ul>
              <p className="mt-4 text-xs leading-relaxed text-muted">Успешные сделки: {snapshot.won} · Отказы: {snapshot.lost}{snapshot.unknown > 0 ? ` · Неизвестный этап: ${snapshot.unknown}` : ""}</p>
            </Card>
          </div>
          {(snapshot.unknown > 0 || snapshot.invalidDate > 0 || snapshot.withoutProbability > 0) && <Card className="!p-4">
            <h2 className="text-sm font-semibold text-ink">Что уточнить в данных</h2>
            <p className="mt-2 text-xs leading-relaxed text-muted">{snapshot.unknown > 0 && <>Неизвестный этап у {snapshot.unknown} сделок — они показаны отдельно и не включены в «В работе». </>}
              {snapshot.invalidDate > 0 && <>Проверьте даты у {snapshot.invalidDate} сделок. </>}
              {snapshot.withoutProbability > 0 && <>В {snapshot.withoutProbability} сделках в работе вероятность не указана. Значение по стадии не подставляется.</>}</p>
          </Card>}
        </>}
      </>}

      <Card className="!p-4 sm:!p-5">
        <h2 className="text-sm font-semibold text-ink">Для полного управленческого обзора</h2>
        <dl className="mt-3 grid gap-4 text-xs sm:grid-cols-2">
          <div><dt className="font-semibold text-muted">План / факт и точность прогноза</dt><dd className="mt-1 leading-relaxed text-muted">Пока не рассчитаны: нужны утверждённые цели, период и правила прогноза.</dd></div>
          <div><dt className="font-semibold text-muted">Деньги и движение за неделю</dt><dd className="mt-1 leading-relaxed text-muted">Пока не подключены: нужны валюта, подтверждённые поступления и история сумм. Успешная сделка сама по себе не подтверждает оплату.</dd></div>
          <div><dt className="font-semibold text-muted">Рекомендации агента</dt><dd className="mt-1 leading-relaxed text-muted">Пока не подключены. Список внимания выше составлен по срокам и полям сделок.</dd></div>
          <div><dt className="font-semibold text-muted">Согласования</dt><dd className="mt-1 leading-relaxed text-muted">В обзоре пока не подключены. Решения принимайте в соответствующей карточке после проверки её данных и прав.</dd></div>
        </dl>
      </Card>
    </div>
  );
}
