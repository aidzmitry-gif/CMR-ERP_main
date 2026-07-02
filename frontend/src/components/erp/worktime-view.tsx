"use client";

import { useEffect, useState } from "react";

// ── Demo data ─────────────────────────────────────────────────────────────────

interface Employee {
  id: number;
  name: string;
  position: string;
  department: string;
  hoursToday: number;
  online: boolean;
}

const EMPLOYEES: Employee[] = [
  { id: 1, name: "Харькович Д.С.", position: "Директор", department: "Руководство", hoursToday: 6.5, online: true },
  { id: 2, name: "Харькович С.Д.", position: "Зам. директора", department: "Руководство", hoursToday: 5.0, online: true },
  { id: 3, name: "Шляхтина А.В.", position: "Менеджер по продажам", department: "Продажи", hoursToday: 7.0, online: true },
  { id: 4, name: "Рязанов К.И.", position: "Менеджер по продажам", department: "Продажи", hoursToday: 3.5, online: false },
  { id: 5, name: "Макаров П.С.", position: "Менеджер по закупкам", department: "Закупки", hoursToday: 8.0, online: true },
  { id: 6, name: "Карчевская О.Н.", position: "Бухгалтер", department: "Финансы", hoursToday: 7.5, online: true },
  { id: 7, name: "Жуковская Е.А.", position: "HR-менеджер", department: "HR", hoursToday: 6.0, online: true },
  { id: 8, name: "Ведерникова Т.В.", position: "Офис-менеджер", department: "Офис", hoursToday: 4.0, online: false },
  { id: 9, name: "Козлов А.М.", position: "Кладовщик", department: "Склад", hoursToday: 8.0, online: true },
  { id: 10, name: "Петров С.Г.", position: "Логист", department: "Логистика", hoursToday: 0, online: false },
  { id: 11, name: "Сидорова М.К.", position: "Менеджер по продажам", department: "Продажи", hoursToday: 7.0, online: true },
  { id: 12, name: "Новиков Д.Р.", position: "Программист", department: "IT", hoursToday: 5.5, online: true },
];

// Demo start time: today 08:30 (fixed for demo)
const SHIFT_START_SECONDS = 8 * 3600 + 30 * 60;

type DayCode = "В" | "О" | "Б" | "К" | "А" | number;

interface TabelRow {
  employeeId: number;
  name: string;
  days: DayCode[];
}

const TABEL: TabelRow[] = [
  { employeeId: 1, name: "Харькович Д.С.", days: [8,8,8,8,8,"В","В",8,8,9,8,8,"В","В",8,8,8,8,9,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 2, name: "Харькович С.Д.", days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 3, name: "Шляхтина А.В.",  days: [8,8,8,9,8,"В","В",8,8,9,8,8,"В","В",10,8,8,8,8,"В","В",8,9,8,8,8,"В","В",8,8] },
  { employeeId: 4, name: "Рязанов К.И.",   days: [8,8,8,8,8,"В","В",8,8,8,"О","О","О","О","О",8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 5, name: "Макаров П.С.",   days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,9,8,"В","В",8,8,8,9,8,"В","В",8,8] },
  { employeeId: 6, name: "Карчевская О.Н.",days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,"Б","Б","Б","Б","Б",8,8] },
  { employeeId: 7, name: "Жуковская Е.А.",  days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 8, name: "Ведерникова Т.В.",days: [8,8,8,8,8,"В","В","К","К","К","К","К",8,8,8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 9, name: "Козлов А.М.",    days: [8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8,8] },
  { employeeId: 10,name: "Петров С.Г.",    days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В","А","А","А","А","А","А","А",8,8] },
  { employeeId: 11,name: "Сидорова М.К.",  days: [8,8,8,9,8,"В","В",8,8,9,10,8,"В","В",8,8,9,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
  { employeeId: 12,name: "Новиков Д.Р.",   days: [8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8,8,8,8,"В","В",8,8] },
];

const CODE_LABEL: Record<string, string> = {
  В: "Выходной",
  О: "Отпуск",
  Б: "Больничный",
  К: "Командировка",
  А: "Административный отпуск",
};

const DEPARTMENTS = ["Все", ...Array.from(new Set(EMPLOYEES.map((e) => e.department)))];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtHMS(totalSec: number): string {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

function nowSeconds(): number {
  const d = new Date();
  return d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds();
}

function dayCode(v: DayCode): string {
  return typeof v === "number" ? String(v) : v;
}

function isOvertime(v: DayCode): boolean {
  return typeof v === "number" && v > 8;
}

// ── Modal ─────────────────────────────────────────────────────────────────────

interface ModalData {
  name: string;
  day: number;
  norm: number;
  actual: number;
}

interface OvertimeModalProps {
  data: ModalData;
  onClose: () => void;
  onApprove: () => void;
  onReject: () => void;
}

function OvertimeModal({ data, onClose, onApprove, onReject }: OvertimeModalProps) {
  const extra = data.actual - data.norm;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-2xl border border-line bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-4 text-base font-semibold text-ink">Согласование переработки</h2>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted">Сотрудник</dt>
            <dd className="font-medium text-ink">{data.name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Дата (день месяца)</dt>
            <dd className="font-medium text-ink">{data.day}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Норма</dt>
            <dd className="text-ink">{data.norm} ч</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Факт</dt>
            <dd className="font-medium text-ink">{data.actual} ч</dd>
          </div>
          <div className="flex justify-between border-t border-line pt-2">
            <dt className="text-muted">Сверхурочно</dt>
            <dd className="font-semibold text-amber-600 dark:text-amber-400">+{extra} ч</dd>
          </div>
        </dl>
        <div className="mt-5 flex gap-3">
          <button
            onClick={onApprove}
            className="flex-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700"
          >
            Согласовать
          </button>
          <button
            onClick={onReject}
            className="flex-1 rounded-lg bg-red-100 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-300"
          >
            Отклонить
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Мой день ─────────────────────────────────────────────────────────────
// Скорборд «Моя выработка» — перенос блока План/Факт с доски Sales (sales-board-mockup.html)
// один-в-один: полоса с разделителями, крупный headline, «/ план», светофор-бар + метка темпа,
// «% выполнено», строка-прогноз run-rate, статус-пилюля темпа, сегменты периода.

type MetricKind = "num" | "pct";

interface Metric {
  label: string;
  fact: number;
  plan: number;
  kind: MetricKind;
  unit?: string;
  headline?: boolean;
  proj?: boolean; // строить прогноз run-rate (не для ставочных: пунктуальность/ср.смена/явка)
}

type PeriodKey = "day" | "week" | "month" | "quarter" | "year";

const PERIODS: { id: PeriodKey; label: string }[] = [
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
  { id: "quarter", label: "Квартал" },
  { id: "year", label: "Год" },
];

// el — % прошедшего времени периода (метка темпа + база прогноза); overtime — чип переработок.
const PERIOD_META: Record<PeriodKey, { el: number; sub: string; overtime: string }> = {
  day: { el: 71, sub: "— сегодня, 02 июля", overtime: "—" },
  week: { el: 80, sub: "— неделя 27 июн – 03 июл", overtime: "+2 ч" },
  month: { el: 71, sub: "— Июль 2026 · норма по контракту 168 ч", overtime: "+3 ч · на согл." },
  quarter: { el: 34, sub: "— III квартал 2026 (июл–сен)", overtime: "+9 ч" },
  year: { el: 50, sub: "— 2026 год", overtime: "+34 ч" },
};

const METRICS: Record<PeriodKey, Metric[]> = {
  day: [
    { label: "Отработано", fact: 5.7, plan: 8, kind: "num", unit: "ч", headline: true, proj: true },
    { label: "Смены", fact: 1, plan: 1, kind: "num", unit: "дн", proj: true },
    { label: "Явка в отделе", fact: 9, plan: 12, kind: "num" },
    { label: "Пунктуальность", fact: 100, plan: 100, kind: "pct" },
    { label: "Ср. смена", fact: 5.7, plan: 8, kind: "num", unit: "ч" },
  ],
  week: [
    { label: "Отработано", fact: 34, plan: 40, kind: "num", unit: "ч", headline: true, proj: true },
    { label: "Смены", fact: 4, plan: 5, kind: "num", unit: "дн", proj: true },
    { label: "Явка в отделе", fact: 10, plan: 12, kind: "num" },
    { label: "Пунктуальность", fact: 98, plan: 100, kind: "pct" },
    { label: "Ср. смена", fact: 8.5, plan: 8, kind: "num", unit: "ч" },
  ],
  month: [
    { label: "Отработано", fact: 142, plan: 168, kind: "num", unit: "ч", headline: true, proj: true },
    { label: "Смены", fact: 15, plan: 21, kind: "num", unit: "дн", proj: true },
    { label: "Явка в отделе", fact: 9, plan: 12, kind: "num" },
    { label: "Пунктуальность", fact: 96, plan: 100, kind: "pct" },
    { label: "Ср. смена", fact: 7.4, plan: 8, kind: "num", unit: "ч" },
  ],
  quarter: [
    { label: "Отработано", fact: 168, plan: 504, kind: "num", unit: "ч", headline: true, proj: true },
    { label: "Смены", fact: 21, plan: 63, kind: "num", unit: "дн", proj: true },
    { label: "Явка в отделе", fact: 10, plan: 12, kind: "num" },
    { label: "Пунктуальность", fact: 95, plan: 100, kind: "pct" },
    { label: "Ср. смена", fact: 7.6, plan: 8, kind: "num", unit: "ч" },
  ],
  year: [
    { label: "Отработано", fact: 980, plan: 1980, kind: "num", unit: "ч", headline: true, proj: true },
    { label: "Смены", fact: 128, plan: 247, kind: "num", unit: "дн", proj: true },
    { label: "Явка в отделе", fact: 10, plan: 12, kind: "num" },
    { label: "Пунктуальность", fact: 96, plan: 100, kind: "pct" },
    { label: "Ср. смена", fact: 7.7, plan: 8, kind: "num", unit: "ч" },
  ],
};

/** Светофор выполнения (как KpiCard, Сделки 2.0): ≥100 зелёный · ≥70 янтарь · иначе красный. */
function tone(pct: number): { bar: string; text: string; dot: string } {
  if (pct >= 100) return { bar: "bg-emerald-500", text: "text-emerald-600 dark:text-emerald-400", dot: "bg-emerald-500" };
  if (pct >= 70) return { bar: "bg-amber-500", text: "text-amber-600 dark:text-amber-400", dot: "bg-amber-500" };
  return { bar: "bg-red-500", text: "text-red-600 dark:text-red-400", dot: "bg-red-500" };
}

/** Цвет прогноза для учёта времени: у нормы (90–110%) — зелёный; выше — переработка (янтарь); ниже — недоработка (красный). */
function projTone(pct: number): string {
  if (pct > 110) return "text-amber-600 dark:text-amber-400";
  if (pct >= 90) return "text-emerald-600 dark:text-emerald-400";
  return "text-red-600 dark:text-red-400";
}

function fmtNum(n: number): string {
  const r = Math.round(n * 10) / 10;
  return Number.isInteger(r)
    ? r.toLocaleString("ru-RU")
    : r.toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function fmtVal(v: number, kind: MetricKind): string {
  return kind === "pct" ? `${v}%` : fmtNum(v);
}

/** Скорборд «Моя выработка» — плотный, разметка как План/Факт на доске Sales. */
function Scoreboard() {
  const [period, setPeriod] = useState<PeriodKey>("month");
  const meta = PERIOD_META[period];
  const metrics = METRICS[period];
  const el = meta.el;

  // Пилюля темпа: выполнение headline (Отработано) против прошедшего времени.
  const head = metrics[0];
  const headPct = Math.round((head.fact / head.plan) * 100);
  const diff = headPct - el;
  const pace =
    diff >= 5
      ? { cls: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300", txt: `Опережаем график на ${diff} п.п.` }
      : diff >= -5
        ? { cls: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300", txt: "Идём в графике" }
        : { cls: "bg-red-50 text-red-600 dark:bg-red-900/30 dark:text-red-300", txt: `Отстаём на ${-diff} п.п.` };

  return (
    <section className="rounded-2xl bg-surface px-4 py-3.5 shadow-card">
      {/* Шапка: заголовок + статус темпа + сегменты периода */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5 text-[15px] font-bold text-ink">
          <span className="h-2 w-2 rounded-full bg-emerald-500 ring-4 ring-emerald-500/15" />
          Моя выработка
          <span className="ml-1 text-xs font-normal text-muted">{meta.sub}</span>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${pace.cls}`}>
            {pace.txt}
            <span className="font-normal opacity-75">· прошло {el}% периода</span>
          </span>
          {meta.overtime !== "—" && (
            <span className="inline-flex items-center rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">
              Переработки {meta.overtime}
            </span>
          )}
        </div>
        <div className="flex gap-0.5 rounded-lg border border-line p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              onClick={() => setPeriod(p.id)}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                period === p.id ? "bg-accent text-white" : "text-muted hover:text-ink"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Полоса метрик: headline шире, разделители между колонками. Прокрутка при нехватке ширины — не сплющивать. */}
      <div className="overflow-x-auto">
      <div
        className="grid min-w-[880px]"
        style={{ gridTemplateColumns: `1.5fr ${"1fr ".repeat(metrics.length - 1).trim()}` }}
      >
        {metrics.map((m, i) => {
          const pct = Math.round((m.fact / m.plan) * 100);
          const t = tone(pct);
          const w = Math.min(pct, 100);
          const projFact = m.proj ? Math.round((m.fact * 100) / el) : 0;
          const projPct = m.proj ? Math.round((projFact / m.plan) * 100) : 0;
          return (
            <div key={m.label} className={`relative px-4 py-1 ${i === 0 ? "pl-1" : "border-l border-line"}`}>
              <div className="whitespace-nowrap text-[11.5px] text-muted">{m.label}</div>
              <div className={`mt-1 font-bold leading-tight tracking-tight text-ink ${m.headline ? "text-[26px]" : "text-lg"}`}>
                {fmtVal(m.fact, m.kind)}
                <span className="text-[12.5px] font-normal text-faint"> / {fmtVal(m.plan, m.kind)}</span>
                {m.unit && <span className="text-[11px] font-normal text-faint"> {m.unit}</span>}
              </div>
              <div className="relative mt-2 h-1.5 overflow-hidden rounded-full bg-sunken">
                <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${w}%` }} />
                <span
                  className="absolute -top-px -bottom-px w-0.5 bg-ink/50"
                  style={{ left: `${Math.min(el, 100)}%` }}
                  title={`нужно к этому дню: ${el}%`}
                />
              </div>
              <div className={`mt-1.5 flex items-center gap-1.5 text-[11px] font-semibold ${t.text}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
                {pct}% выполнено
              </div>
              {m.proj && (
                <div className="mt-1 text-[10.5px] text-muted">
                  → идём на{" "}
                  <span className="font-bold text-ink">
                    {fmtNum(projFact)}
                    {m.unit ? ` ${m.unit}` : ""}
                  </span>{" "}
                  <span className={`font-bold ${projTone(projPct)}`}>({projPct}%)</span>
                </div>
              )}
            </div>
          );
        })}
      </div>
      </div>
    </section>
  );
}

function MyDayTab() {
  const [elapsed, setElapsed] = useState(0);
  const [active, setActive] = useState(true);

  useEffect(() => {
    if (!active) return;
    const tick = () => {
      const now = nowSeconds();
      setElapsed(Math.max(0, now - SHIFT_START_SECONDS));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [active]);

  const normSec = 8 * 3600;
  const progress = Math.min(100, (elapsed / normSec) * 100);
  const hoursElapsed = elapsed / 3600;

  return (
    <div className="flex flex-col gap-4">
      {/* Таймер смены — компактная полоса (личные «часы»: старт/счётчик/стоп) */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-2xl bg-surface px-5 py-4 shadow-card">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Текущая смена</div>
          <div className="mt-0.5 font-mono text-3xl font-bold tabular-nums text-ink">{fmtHMS(elapsed)}</div>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${active ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-300" : "bg-sunken text-muted"}`}>
          ● {active ? "смена идёт" : "смена завершена"}
        </span>
        {active ? (
          <button
            onClick={() => setActive(false)}
            className="rounded-lg bg-red-100 px-4 py-2 text-sm font-medium text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-300"
          >
            Завершить день
          </button>
        ) : (
          <span className="rounded-lg bg-emerald-100 px-4 py-2 text-sm font-medium text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
            День завершён
          </span>
        )}
        <div className="min-w-[180px] flex-1">
          <div className="flex items-center justify-between text-xs text-muted">
            <span>Начало 08:30</span>
            <span>{hoursElapsed.toFixed(1)} / 8 ч</span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-sunken">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-1 text-[11px] text-muted">План завершения — 16:30</div>
        </div>
      </div>

      {/* Скорборд «Моя выработка» — плотный, стиль План/Факт */}
      <Scoreboard />

      {/* Напоминание */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-700/40 dark:bg-amber-900/20 dark:text-amber-300">
        Не забудьте завершить смену до 18:00 — иначе система зафиксирует max 10 ч.
      </div>
    </div>
  );
}

// ── Tab: Кто онлайн ───────────────────────────────────────────────────────────

function OnlineTab() {
  const [dept, setDept] = useState("Все");

  const visible = dept === "Все" ? EMPLOYEES : EMPLOYEES.filter((e) => e.department === dept);
  const onlineCount = EMPLOYEES.filter((e) => e.online).length;

  return (
    <div className="flex flex-col gap-4">
      {/* Фильтры */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-muted">
          {onlineCount} / {EMPLOYEES.length} онлайн
        </span>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {DEPARTMENTS.map((d) => (
            <button
              key={d}
              onClick={() => setDept(d)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                dept === d
                  ? "bg-accent text-white"
                  : "bg-sunken text-muted hover:bg-line hover:text-ink"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* Список сотрудников */}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line bg-sunken text-xs text-muted">
              <th className="px-4 py-3 text-left font-medium">Сотрудник</th>
              <th className="px-4 py-3 text-left font-medium">Отдел</th>
              <th className="px-4 py-3 text-left font-medium">Должность</th>
              <th className="px-4 py-3 text-right font-medium">Часов сегодня</th>
              <th className="px-4 py-3 text-center font-medium">Статус</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {visible.map((e) => (
              <tr key={e.id} className="hover:bg-sunken/50">
                <td className="px-4 py-3 font-medium text-ink">{e.name}</td>
                <td className="px-4 py-3 text-muted">{e.department}</td>
                <td className="px-4 py-3 text-muted">{e.position}</td>
                <td className="px-4 py-3 text-right font-mono text-ink">
                  {e.online ? e.hoursToday.toFixed(1) : e.hoursToday > 0 ? e.hoursToday.toFixed(1) : "—"}
                </td>
                <td className="px-4 py-3 text-center">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      e.online
                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                        : "bg-gray-100 text-gray-500 dark:bg-gray-800/40 dark:text-gray-400"
                    }`}
                  >
                    {e.online ? "Онлайн" : "Офлайн"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Tab: Табель ───────────────────────────────────────────────────────────────

interface OvertimeApproval {
  employeeId: number;
  day: number;
  status: "pending" | "approved" | "rejected";
}

function TabelTab() {
  const days = Array.from({ length: 30 }, (_, i) => i + 1);
  const [modal, setModal] = useState<ModalData | null>(null);
  const [approvals, setApprovals] = useState<OvertimeApproval[]>(() => {
    const list: OvertimeApproval[] = [];
    TABEL.forEach((row) => {
      row.days.forEach((v, i) => {
        if (isOvertime(v)) {
          list.push({ employeeId: row.employeeId, day: i + 1, status: "pending" });
        }
      });
    });
    return list;
  });

  function getApproval(employeeId: number, day: number) {
    return approvals.find((a) => a.employeeId === employeeId && a.day === day);
  }

  function setApprovalStatus(employeeId: number, day: number, status: "approved" | "rejected") {
    setApprovals((prev) =>
      prev.map((a) => (a.employeeId === employeeId && a.day === day ? { ...a, status } : a))
    );
    setModal(null);
  }

  function cellClass(v: DayCode, approval?: OvertimeApproval): string {
    if (typeof v === "string") return "text-blue-600 dark:text-blue-400 font-medium";
    if (v > 8) {
      if (approval?.status === "approved") return "text-emerald-700 dark:text-emerald-400 font-bold cursor-pointer";
      if (approval?.status === "rejected") return "text-gray-400 line-through cursor-pointer";
      return "text-amber-600 dark:text-amber-400 font-bold cursor-pointer";
    }
    return "text-ink";
  }

  function totalDays(row: TabelRow): number {
    return row.days.filter((v) => typeof v === "number").length;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ink">Табель рабочего времени — Июль 2026</h3>
        <button
          disabled
          title="Функция в разработке"
          className="rounded-lg border border-line px-4 py-1.5 text-sm text-muted opacity-50 cursor-not-allowed"
        >
          Экспорт T-13
        </button>
      </div>

      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-sm">
        <table className="min-w-max text-xs">
          <thead>
            <tr className="border-b border-line bg-sunken text-muted">
              <th className="sticky left-0 z-10 bg-sunken px-4 py-3 text-left font-medium min-w-[160px]">
                Сотрудник
              </th>
              {days.map((d) => (
                <th key={d} className="px-2 py-3 text-center font-medium w-8">
                  {d}
                </th>
              ))}
              <th className="px-3 py-3 text-center font-medium">Дни</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {TABEL.map((row) => (
              <tr key={row.employeeId} className="hover:bg-sunken/50">
                <td className="sticky left-0 z-10 bg-surface px-4 py-2 font-medium text-ink whitespace-nowrap hover:bg-sunken/50">
                  {row.name}
                </td>
                {row.days.map((v, i) => {
                  const approval = isOvertime(v) ? getApproval(row.employeeId, i + 1) : undefined;
                  return (
                    <td
                      key={i}
                      className={`px-2 py-2 text-center ${cellClass(v, approval)}`}
                      title={
                        typeof v === "string"
                          ? CODE_LABEL[v]
                          : isOvertime(v)
                            ? `Переработка: ${v}ч (норма 8ч). Клик — согласовать`
                            : undefined
                      }
                      onClick={() => {
                        if (isOvertime(v)) {
                          setModal({
                            name: row.name,
                            day: i + 1,
                            norm: 8,
                            actual: v as number,
                          });
                        }
                      }}
                    >
                      {dayCode(v)}
                    </td>
                  );
                })}
                <td className="px-3 py-2 text-center font-medium text-ink">{totalDays(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Легенда */}
      <div className="flex flex-wrap gap-4 text-xs text-muted">
        {Object.entries(CODE_LABEL).map(([code, label]) => (
          <span key={code}>
            <span className="font-semibold text-blue-600 dark:text-blue-400">{code}</span> — {label}
          </span>
        ))}
        <span>
          <span className="font-semibold text-amber-600 dark:text-amber-400">9/10</span> — Переработка (кликабельно)
        </span>
      </div>

      {/* Модалка согласования */}
      {modal && (
        <OvertimeModal
          data={modal}
          onClose={() => setModal(null)}
          onApprove={() => {
            const row = TABEL.find((r) => r.name === modal.name);
            if (row) setApprovalStatus(row.employeeId, modal.day, "approved");
          }}
          onReject={() => {
            const row = TABEL.find((r) => r.name === modal.name);
            if (row) setApprovalStatus(row.employeeId, modal.day, "rejected");
          }}
        />
      )}
    </div>
  );
}

// ── Root component ────────────────────────────────────────────────────────────

type Tab = "myday" | "online" | "tabel";

const TABS: { id: Tab; label: string }[] = [
  { id: "myday", label: "Мой день" },
  { id: "online", label: "Кто онлайн" },
  { id: "tabel", label: "Табель (T-13)" },
];

export function WorktimeView() {
  const [tab, setTab] = useState<Tab>("myday");

  return (
    <div className="flex flex-1 flex-col gap-5 overflow-auto p-6">
      {/* Вкладки */}
      <div className="flex gap-1 rounded-xl border border-line bg-sunken p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
              tab === t.id
                ? "bg-surface text-ink shadow-sm"
                : "text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Контент */}
      {tab === "myday" && <MyDayTab />}
      {tab === "online" && <OnlineTab />}
      {tab === "tabel" && <TabelTab />}
    </div>
  );
}
