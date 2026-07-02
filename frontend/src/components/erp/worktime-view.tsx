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
  const monthHours = 142;
  const monthNorm = 168;
  const overtimeHours = 3;

  return (
    <div className="flex flex-col gap-5">
      {/* Таймер смены */}
      <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
        <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
          Текущая смена
        </div>
        <div className="mb-3 font-mono text-4xl font-bold text-ink tabular-nums">
          {fmtHMS(elapsed)}
        </div>
        <div className="mb-3 h-2 overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="mb-4 flex items-center justify-between text-xs text-muted">
          <span>Начало: 08:30</span>
          <span>{hoursElapsed.toFixed(1)} / 8 ч</span>
        </div>
        {active ? (
          <button
            onClick={() => setActive(false)}
            className="rounded-lg bg-red-100 px-5 py-2 text-sm font-medium text-red-700 hover:bg-red-200 dark:bg-red-900/30 dark:text-red-300"
          >
            Завершить день
          </button>
        ) : (
          <div className="rounded-lg bg-emerald-100 px-4 py-2 text-sm font-medium text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
            Рабочий день завершён
          </div>
        )}
      </div>

      {/* Напоминание */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700/40 dark:bg-amber-900/20 dark:text-amber-300">
        Не забудьте завершить смену до 18:00 — иначе система зафиксирует max 10 ч.
      </div>

      {/* Статистика */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Сегодня онлайн", value: `${EMPLOYEES.filter((e) => e.online).length} / ${EMPLOYEES.length}`, accent: false },
          { label: "Месяц", value: `${monthHours} / ${monthNorm} ч`, accent: false },
          { label: "Переработки", value: `+${overtimeHours} ч`, sub: "на согласовании", accent: true },
          { label: "Статус", value: "Рабочий день", sub: "без командировок", accent: false },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
            <div className="mb-1 text-xs text-muted">{s.label}</div>
            <div className={`text-lg font-bold ${s.accent ? "text-amber-600 dark:text-amber-400" : "text-ink"}`}>
              {s.value}
            </div>
            {s.sub && <div className="mt-0.5 text-xs text-muted">{s.sub}</div>}
          </div>
        ))}
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
