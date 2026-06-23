"use client";

import {
  ArrowUpRight,
  Boxes,
  CheckCircle2,
  Link2,
  Recycle,
  Send,
  Truck,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";
import { formatByn, formatNumber } from "@/lib/format";

// База, согласованная с РОПом (вал. прибыль, BYN).
const BASE = 75000;

// demo-данные (бэкенда по экрану пока нет)
type CommittedRow = {
  nm: string;
  sub: string;
  when: string;
  rev: number;
  pf: number;
  on: boolean;
};

type RegularRow = {
  nm: string;
  cadence: string;
  when: string;
  julyExp: boolean;
  check: number;
  prob: number;
  pf: number;
  on: boolean;
};

// demo-данные (бэкенда по экрану пока нет) — под приходящий товar (логистика + закупки)
const COMMITTED_SEED: CommittedRow[] = [
  { nm: "АКБ 6СТ-190 (перезаказ Белтранс)", sub: "рейс TR-0430 · под CRM-1029", when: "05.07", rev: 52000, pf: 19200, on: true },
  { nm: "АКБ годовой объём — Автопарк №7", sub: "рейс TR-0433 · под CRM-1024", when: "12.07", rev: 54000, pf: 19500, on: false },
  { nm: "АКБ для МЧС (тендер)", sub: "рейс TR-0436 · быстрый приход", when: "20.07", rev: 92000, pf: 32800, on: false },
];

// demo-данные (бэкенда по экрану пока нет) — постоянные клиенты (прогноз по периодичности)
const REGULARS_SEED: RegularRow[] = [
  { nm: "ТЧУП «Энергомир»", cadence: "цикл ~100 дн · посл. 09.04", when: "~18.07", julyExp: true, check: 31600, prob: 80, pf: 12200, on: true },
  { nm: "СТО «Гранд-Сервис»", cadence: "цикл ~45 дн · посл. 30.05", when: "~15.07", julyExp: true, check: 14800, prob: 85, pf: 5400, on: false },
  { nm: "РУП «Белводхоз»", cadence: "цикл ~60 дн · посл. 28.05", when: "~27.07", julyExp: true, check: 52400, prob: 70, pf: 17400, on: false },
  { nm: "ОАО «Нафтан»", cadence: "цикл ~120 дн · посл. 15.03", when: "~10.07", julyExp: true, check: 62800, prob: 65, pf: 19000, on: false },
  { nm: "УП «Минскэлектро»", cadence: "цикл ~70 дн · посл. 25.05", when: "~28.07", julyExp: true, check: 38900, prob: 75, pf: 12500, on: false },
  { nm: "ЧТУП «АвтоМир»", cadence: "цикл ~75 дн · посл. 06.05", when: "~20.07", julyExp: true, check: 9200, prob: 50, pf: 2800, on: false },
  { nm: "ОДО «ВодоканалСервис»", cadence: "цикл ~90 дн · посл. 02.06", when: "~31.08", julyExp: false, check: 27300, prob: 60, pf: 9000, on: false },
  { nm: "ИП Ковальчук", cadence: "цикл ~50 дн · посл. 12.06", when: "~01.08", julyExp: false, check: 3200, prob: 55, pf: 1100, on: false },
];

// demo-данные (бэкенда по экрану пока нет) — стартовые значения калькулятора активности
const CALC_SEED = {
  leads: 30,
  leadConv: 12,
  calls: 150,
  callConv: 1.5,
  check: 16000,
  margin: 34,
};

function pctOfBase(value: number): number {
  return Math.round((value / BASE) * 100);
}

export function PlanBuilder() {
  const [committed, setCommitted] = useState<CommittedRow[]>(COMMITTED_SEED);
  const [regulars, setRegulars] = useState<RegularRow[]>(REGULARS_SEED);
  const [calc, setCalc] = useState(CALC_SEED);

  // --- источник 1: под приходящий товар ---
  const s1 = useMemo(() => {
    let pf = 0;
    let rev = 0;
    let count = 0;
    for (const r of committed) {
      if (r.on) {
        pf += r.pf;
        rev += r.rev;
        count += 1;
      }
    }
    return { pf, rev, count };
  }, [committed]);

  // --- источник 2: постоянные клиенты ---
  const s2 = useMemo(() => {
    let pf = 0;
    let rev = 0;
    let count = 0;
    for (const r of regulars) {
      if (r.on) {
        pf += r.pf;
        rev += r.check;
        count += 1;
      }
    }
    return { pf, rev, count };
  }, [regulars]);

  // --- источник 3: калькулятор новых по действиям ---
  const s3 = useMemo(() => {
    const dealsLeads = (calc.leads * calc.leadConv) / 100;
    const dealsCalls = (calc.calls * calc.callConv) / 100;
    const deals = dealsLeads + dealsCalls;
    const rev = deals * calc.check;
    const pf = (rev * calc.margin) / 100;
    const perDeal = (calc.check * calc.margin) / 100;
    return { deals, rev, pf, perDeal };
  }, [calc]);

  const assembled = s1.pf + s2.pf + s3.pf;
  const diff = assembled - BASE;
  const planSuggested = Math.round(assembled / 1000) * 1000;

  // масштаб полосы композиции — максимум из собранного и базы
  const scale = Math.max(assembled, BASE) || 1;
  const segments = [
    { key: "s1", label: "Под товар", value: s1.pf, cls: "bg-blue-500" },
    { key: "s2", label: "Постоянные", value: s2.pf, cls: "bg-emerald-500" },
    { key: "s3", label: "Новые (по действиям)", value: s3.pf, cls: "bg-amber-500" },
  ];

  const julyRegulars = regulars
    .map((r, i) => ({ r, i }))
    .filter((x) => x.r.julyExp);
  const otherRegulars = regulars
    .map((r, i) => ({ r, i }))
    .filter((x) => !x.r.julyExp);

  const [sent, setSent] = useState(false);

  function toggleCommitted(idx: number, on: boolean) {
    setCommitted((prev) => prev.map((r, i) => (i === idx ? { ...r, on } : r)));
  }
  function setCommittedPf(idx: number, pf: number) {
    setCommitted((prev) => prev.map((r, i) => (i === idx ? { ...r, pf } : r)));
  }
  function toggleRegular(idx: number, on: boolean) {
    setRegulars((prev) => prev.map((r, i) => (i === idx ? { ...r, on } : r)));
  }
  function setRegularPf(idx: number, pf: number) {
    setRegulars((prev) => prev.map((r, i) => (i === idx ? { ...r, pf } : r)));
  }

  // обратный счёт по новым: сколько ещё заявок/звонков нужно, чтобы закрыть дефицит
  const need = diff < 0 && s3.perDeal > 0 ? -diff / s3.perDeal : 0;
  const needLeads =
    calc.leadConv > 0 ? Math.ceil(need / (calc.leadConv / 100)) : 0;
  const needCalls =
    calc.callConv > 0 ? Math.ceil(need / (calc.callConv / 100)) : 0;

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div>
          <h1 className="text-xl font-bold text-ink">
            Мой план на июль · конструктор + декомпозиция
          </h1>
          <p className="mt-1 text-sm text-muted">
            План собирается из источников ERP и считается по действиям (заявки маркетинга, звонки,
            конверсия, средний чек) · валовая прибыль, BYN
          </p>
        </div>

        {/* Скорборд: база / собрано / вердикт + полоса композиции */}
        <div className="rounded-2xl bg-surface p-5 shadow-card">
          <div className="flex flex-wrap items-end gap-6">
            <div>
              <div className="text-[11px] text-muted">База — согласовано с РОПом</div>
              <div className="mt-0.5 text-2xl font-bold tabular-nums text-ink">{formatByn(BASE)}</div>
            </div>
            <div>
              <div className="text-[11px] text-muted">Собрано из источников</div>
              <div className="mt-0.5 text-2xl font-bold tabular-nums text-accent-ink">
                {formatByn(assembled)}
              </div>
            </div>
            <div className="ml-auto text-right">
              {diff >= 0 ? (
                <span className="inline-block rounded-full bg-emerald-50 px-3.5 py-1.5 text-sm font-bold text-emerald-600">
                  План набран
                </span>
              ) : (
                <span className="inline-block rounded-full bg-red-50 px-3.5 py-1.5 text-sm font-bold text-red-600">
                  Дефицит {formatByn(-diff)}
                </span>
              )}
              <div className="mt-1.5 text-[11px] text-faint">
                {diff >= 0
                  ? `перекрывают базу на ${formatByn(diff)}`
                  : `собрано ${pctOfBase(assembled)}% базы`}
              </div>
            </div>
          </div>

          {/* Полоса композиции с линией плана РОПа */}
          <div className="relative mt-5">
            <div className="flex h-6 overflow-hidden rounded-xl bg-sunken">
              {segments.map((seg) =>
                seg.value > 0 ? (
                  <div
                    key={seg.key}
                    className={`h-full transition-all ${seg.cls}`}
                    style={{ width: `${(seg.value / scale) * 100}%` }}
                  />
                ) : null,
              )}
              {assembled < BASE && (
                <div
                  className="h-full bg-red-100"
                  style={{ width: `${((BASE - assembled) / scale) * 100}%` }}
                />
              )}
            </div>
            {/* Линия плана РОПа */}
            <div
              className="absolute -top-1 bottom-[-4px] w-0.5 bg-ink"
              style={{ left: `${(BASE / scale) * 100}%` }}
            >
              <span className="absolute -top-4 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-surface px-1 text-[10px] font-bold text-ink">
                план РОПа
              </span>
            </div>
          </div>

          {/* Легенда */}
          <div className="mt-4 flex flex-wrap gap-4 text-[11px]">
            <LegendItem cls="bg-blue-500" label="Под товар" />
            <LegendItem cls="bg-emerald-500" label="Постоянные" />
            <LegendItem cls="bg-amber-500" label="Новые (по действиям)" />
            <LegendItem cls="bg-red-100" label="дефицит" />
          </div>
        </div>

        {/* 1. Под приходящий товар */}
        <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
          <SourceHeader
            icon={<Boxes size={18} />}
            iconCls="bg-blue-50 text-blue-600"
            title="Под приходящий товар"
            badge="из логистики + закупок"
            sub="Позиции, которые точно приедут в машинах июля"
            count={s1.count}
            unit="поз"
            rev={s1.rev}
            pf={s1.pf}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="bg-sunken text-[10px] uppercase tracking-wide text-faint">
                  <th className="w-10 px-4 py-2" />
                  <th className="px-4 py-2 text-left font-semibold">Товар / под кого</th>
                  <th className="px-4 py-2 text-left font-semibold">Придёт</th>
                  <th className="px-4 py-2 text-right font-semibold">Выручка</th>
                  <th className="px-4 py-2 text-right font-semibold">План, вал. приб.</th>
                </tr>
              </thead>
              <tbody>
                {committed.map((r, i) => (
                  <tr
                    key={r.nm}
                    className={`border-t border-line ${r.on ? "" : "opacity-40"}`}
                  >
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        checked={r.on}
                        onChange={(e) => toggleCommitted(i, e.target.checked)}
                        className="h-4 w-4 cursor-pointer accent-accent"
                        aria-label={`Учитывать ${r.nm}`}
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="font-semibold text-ink">{r.nm}</div>
                      <div className="text-[11px] text-faint">{r.sub}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-600">
                        <Truck size={12} /> придёт {r.when}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums text-ink">
                      {formatByn(r.rev)}
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <input
                        type="number"
                        value={r.pf}
                        onChange={(e) => setCommittedPf(i, Number(e.target.value) || 0)}
                        className="w-28 rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-semibold tabular-nums text-ink outline-none focus:border-accent"
                        aria-label={`План прибыли ${r.nm}`}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 2. Постоянные клиенты — база */}
        <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
          <SourceHeader
            icon={<Recycle size={18} />}
            iconCls="bg-emerald-50 text-emerald-600"
            title="Постоянные клиенты — база"
            badge="прогноз по периодичности"
            sub={`${regulars.length} клиентов в базе · ${julyRegulars.length} ждём в июле, ${otherRegulars.length} — позже`}
            count={s2.count}
            unit="клиент."
            rev={s2.rev}
            pf={s2.pf}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="bg-sunken text-[10px] uppercase tracking-wide text-faint">
                  <th className="w-10 px-4 py-2" />
                  <th className="px-4 py-2 text-left font-semibold">Клиент</th>
                  <th className="px-4 py-2 text-left font-semibold">Ожид. заказ</th>
                  <th className="px-4 py-2 text-right font-semibold">Ср. чек</th>
                  <th className="px-4 py-2 text-right font-semibold">Вер-ть</th>
                  <th className="px-4 py-2 text-right font-semibold">План, вал. приб.</th>
                </tr>
              </thead>
              <tbody>
                <GroupRow label={`Ожидаются в июле — ${julyRegulars.length}`} tone="emerald" />
                {julyRegulars.map(({ r, i }) => (
                  <RegularTr
                    key={r.nm}
                    row={r}
                    onToggle={(on) => toggleRegular(i, on)}
                    onPf={(pf) => setRegularPf(i, pf)}
                  />
                ))}
                <GroupRow
                  label={`Вне июля — ${otherRegulars.length} · можно предложить раньше (акция/допродажа)`}
                  tone="amber"
                />
                {otherRegulars.map(({ r, i }) => (
                  <RegularTr
                    key={r.nm}
                    row={r}
                    onToggle={(on) => toggleRegular(i, on)}
                    onPf={(pf) => setRegularPf(i, pf)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 3. Новые клиенты — калькулятор по действиям */}
        <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
          <SourceHeader
            icon={<Zap size={18} />}
            iconCls="bg-amber-50 text-amber-600"
            title="Новые клиенты — план по действиям"
            badge="маркетинг + звонки"
            sub="Сколько сделок/прибыли дают заявки и звонки при вашей конверсии и среднем чеке"
            count={s3.deals.toFixed(1)}
            unit="сдел."
            rev={s3.rev}
            pf={s3.pf}
          />
          <div className="p-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <CalcField
                label="Заявки от маркетинга, шт/мес"
                from="маркетинг"
                value={calc.leads}
                onChange={(v) => setCalc((c) => ({ ...c, leads: v }))}
              />
              <CalcField
                label="Конверсия заявка → сделка, %"
                value={calc.leadConv}
                onChange={(v) => setCalc((c) => ({ ...c, leadConv: v }))}
              />
              <CalcField
                label="Холодные звонки, шт/мес"
                from="менеджер"
                value={calc.calls}
                onChange={(v) => setCalc((c) => ({ ...c, calls: v }))}
              />
              <CalcField
                label="Конверсия звонок → сделка, %"
                value={calc.callConv}
                onChange={(v) => setCalc((c) => ({ ...c, callConv: v }))}
              />
              <CalcField
                label="Средний чек, BYN"
                value={calc.check}
                onChange={(v) => setCalc((c) => ({ ...c, check: v }))}
              />
              <CalcField
                label="Маржа (вал. прибыль), %"
                value={calc.margin}
                onChange={(v) => setCalc((c) => ({ ...c, margin: v }))}
              />
            </div>

            {/* Итоги калькулятора */}
            <div className="mt-4 flex flex-wrap gap-3 border-t border-line pt-4">
              <div className="flex-1 min-w-[120px] rounded-xl bg-sunken p-3 text-center">
                <div className="text-[11px] text-muted">Сделок (новые)</div>
                <div className="mt-0.5 text-xl font-bold tabular-nums text-ink">
                  {s3.deals.toFixed(1)}
                </div>
              </div>
              <div className="flex-1 min-w-[120px] rounded-xl bg-accent-soft p-3 text-center">
                <div className="text-[11px] text-accent-ink">Выручка</div>
                <div className="mt-0.5 text-xl font-bold tabular-nums text-accent-ink">
                  {formatByn(s3.rev)}
                </div>
              </div>
              <div className="flex-1 min-w-[120px] rounded-xl bg-money-soft p-3 text-center">
                <div className="text-[11px] text-money">Вал. прибыль</div>
                <div className="mt-0.5 text-xl font-bold tabular-nums text-money">
                  {formatByn(s3.pf)}
                </div>
              </div>
            </div>

            {/* Обратный счёт */}
            {diff >= 0 ? (
              <div className="mt-3 flex items-start gap-2 rounded-xl bg-emerald-50 p-3 text-[12.5px] text-emerald-600">
                <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
                <span>
                  Источники закрывают план. Текущая активность ({calc.leads} заявок + {calc.calls}{" "}
                  звонков) даёт {s3.deals.toFixed(0)} новых сделок — этого хватает.
                </span>
              </div>
            ) : (
              <div className="mt-3 rounded-xl bg-amber-50 p-3 text-[12.5px] text-amber-600">
                Чтобы закрыть дефицит <b>{formatByn(-diff)}</b> при ср. чеке {formatByn(calc.check)} и
                марже {calc.margin}% нужно ещё <b>~{need.toFixed(1)} новых сделок</b> → это{" "}
                <b>+{needLeads} заявок</b> от маркетинга <b>или +{needCalls} звонков</b> (или
                комбинация). Подними цифры в калькуляторе.
              </div>
            )}
          </div>
        </div>

        {/* Футер: план + отправка */}
        <div className="flex flex-wrap items-center gap-4 rounded-2xl bg-surface p-5 shadow-card">
          <div className="text-[12.5px] text-muted">
            Источники и калькулятор считаются вживую. План можно поднять выше — взять обязательство
            добрать.
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-[12.5px] font-semibold text-muted">План на июль (вал. приб.)</span>
            <span className="rounded-xl border border-line bg-surface px-3 py-2 text-sm font-bold tabular-nums text-ink">
              {formatByn(planSuggested)}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setSent(true)}
            disabled={sent}
            className="inline-flex items-center gap-1.5 rounded-xl bg-accent px-4 py-2.5 text-sm font-bold text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Send size={15} /> {sent ? "Отправлено" : "Отправить РОПу"}
          </button>
          {sent && (
            <span className="text-[12.5px] font-bold text-amber-600">
              Отправлено — на согласовании у РОПа
            </span>
          )}
        </div>

        {/* Подвал-сноска об источниках данных */}
        <div className="flex items-start gap-2 px-0.5 text-xs text-faint">
          <Link2 size={14} className="mt-0.5 shrink-0" />
          <span>
            Данные: <b className="text-ink">заявки — маркетинг</b>,{" "}
            <b className="text-ink">приход/ETA — логистика</b>,{" "}
            <b className="text-ink">landed cost — закупки</b>,{" "}
            <b className="text-ink">перезаказы и конверсия — история сделок</b>. Калькулятор
            показывает план новых от активности; обратный счёт — сколько ещё заявок/звонков нужно,
            чтобы закрыть дефицит до плана РОПа.
          </span>
        </div>
      </div>
    </main>
  );
}

function LegendItem({ cls, label }: { cls: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-muted">
      <span className={`h-2.5 w-2.5 rounded-sm ${cls}`} />
      {label}
    </span>
  );
}

function SourceHeader({
  icon,
  iconCls,
  title,
  badge,
  sub,
  count,
  unit,
  rev,
  pf,
}: {
  icon: React.ReactNode;
  iconCls: string;
  title: string;
  badge: string;
  sub: string;
  count: number | string;
  unit: string;
  rev: number;
  pf: number;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${iconCls}`}>
        {icon}
      </span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2 font-bold text-ink">
          {title}
          <span className="rounded-md bg-sunken px-2 py-0.5 text-[10.5px] font-semibold text-muted">
            {badge}
          </span>
        </div>
        <div className="mt-0.5 text-[11px] text-faint">{sub}</div>
      </div>
      <div className="ml-auto flex gap-5 text-right">
        <StatCell label="в плане" value={`${count} ${unit}`} />
        <StatCell label="выручка" value={formatNumber(Math.round(rev))} />
        <StatCell label="вал. приб." value={formatNumber(Math.round(pf))} tone="money" />
        <StatCell label="доля плана" value={`${pctOfBase(pf)}%`} tone="accent" />
      </div>
    </div>
  );
}

function StatCell({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "money" | "accent";
}) {
  const cls =
    tone === "money" ? "text-money" : tone === "accent" ? "text-accent-ink" : "text-ink";
  return (
    <div>
      <div className="text-[9.5px] uppercase tracking-wide text-faint">{label}</div>
      <div className={`mt-0.5 text-[15px] font-bold tabular-nums ${cls}`}>{value}</div>
    </div>
  );
}

function GroupRow({ label, tone }: { label: string; tone: "emerald" | "amber" }) {
  const cls = tone === "emerald" ? "text-emerald-600" : "text-amber-600";
  return (
    <tr className="bg-sunken">
      <td
        colSpan={6}
        className={`border-t border-line px-4 py-2 text-[11px] font-bold uppercase tracking-wide ${cls}`}
      >
        {label}
      </td>
    </tr>
  );
}

function RegularTr({
  row,
  onToggle,
  onPf,
}: {
  row: RegularRow;
  onToggle: (on: boolean) => void;
  onPf: (pf: number) => void;
}) {
  return (
    <tr className={`border-t border-line ${row.on ? "" : "opacity-40"}`}>
      <td className="px-4 py-2.5">
        <input
          type="checkbox"
          checked={row.on}
          onChange={(e) => onToggle(e.target.checked)}
          className="h-4 w-4 cursor-pointer accent-accent"
          aria-label={`Учитывать ${row.nm}`}
        />
      </td>
      <td className="px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5 font-semibold text-ink">
          {row.nm}
          {!row.julyExp && (
            <span className="inline-flex items-center gap-0.5 rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-bold text-accent-ink">
              <ArrowUpRight size={11} /> подтянуть раньше
            </span>
          )}
        </div>
        <div className="text-[11px] text-faint">{row.cadence}</div>
      </td>
      <td className={`px-4 py-2.5 text-[11px] ${row.julyExp ? "text-muted" : "text-faint"}`}>
        {row.when}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatByn(row.check)}</td>
      <td className="px-4 py-2.5 text-right">
        <span className="inline-block rounded bg-blue-50 px-1.5 py-0.5 text-[10.5px] font-bold text-blue-600">
          {row.prob}%
        </span>
      </td>
      <td className="px-4 py-2.5 text-right">
        <input
          type="number"
          value={row.pf}
          onChange={(e) => onPf(Number(e.target.value) || 0)}
          className="w-28 rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-semibold tabular-nums text-ink outline-none focus:border-accent"
          aria-label={`План прибыли ${row.nm}`}
        />
      </td>
    </tr>
  );
}

function CalcField({
  label,
  from,
  value,
  onChange,
}: {
  label: string;
  from?: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="rounded-xl border border-line bg-sunken px-3 py-2.5">
      <label className="mb-1.5 block text-[11px] text-muted">
        {label}
        {from && (
          <span className="ml-1 rounded bg-accent-soft px-1 py-0.5 text-[9.5px] font-bold text-accent-ink">
            {from}
          </span>
        )}
      </label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(Number(e.target.value) || 0)}
        className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-right text-sm font-bold tabular-nums text-ink outline-none focus:border-accent"
        aria-label={label}
      />
    </div>
  );
}
