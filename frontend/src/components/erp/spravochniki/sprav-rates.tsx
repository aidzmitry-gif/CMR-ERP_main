"use client";

import { useState } from "react";
import { CalendarDays, Clock, Percent, Plus } from "lucide-react";
import {
  type CurrencyRateRow,
  type VatRateRow,
  addRateVersion,
  currencyRateAsOf,
  sortVersionsDesc,
} from "@/lib/reference-data";
import { formatDate, versionStatus, type VersionStatus } from "@/lib/spravochniki-rates";

interface Props {
  initialCurrencyRates: CurrencyRateRow[];
  initialVatRates: VatRateRow[];
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function StatusBadge({ s }: { s: VersionStatus }) {
  if (s === "current")
    return (
      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] text-emerald-700">
        Активна
      </span>
    );
  if (s === "planned")
    return (
      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
        Запланирована
      </span>
    );
  return (
    <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
      🗃 архив
    </span>
  );
}

function barClass(s: VersionStatus) {
  if (s === "current")
    return "flex h-12 items-center justify-center gap-1.5 rounded-lg bg-accent text-sm font-semibold text-white shadow-card";
  if (s === "planned")
    return "flex h-12 items-center justify-center gap-1.5 rounded-lg border border-dashed bg-amber-50 text-sm font-semibold text-amber-700 ring-1 ring-amber-300 ring-inset";
  return "flex h-12 items-center justify-center rounded-lg bg-line-strong text-sm font-semibold text-muted";
}

type BarItem<T> = { row: T; status: VersionStatus; w: number };

function computeBars<T extends { start_date: string; end_date: string | null }>(
  rows: T[],
  today: string,
): BarItem<T>[] {
  const sorted = [...rows].sort((a, b) => a.start_date.localeCompare(b.start_date));
  if (!sorted.length) return [];
  const openEndMs = new Date(today).getTime() + 60 * 86_400_000;
  const endMs = (r: T) =>
    r.end_date ? new Date(r.end_date).getTime() : openEndMs;
  const minMs = new Date(sorted[0].start_date).getTime();
  const maxMs = Math.max(...sorted.map(endMs));
  const span = Math.max(maxMs - minMs, 1);
  return sorted.map((r) => ({
    row: r,
    status: versionStatus(r, today),
    w: Math.max(5, Math.round(((endMs(r) - new Date(r.start_date).getTime()) / span) * 100)),
  }));
}

// ── Component ────────────────────────────────────────────────────────────────

export function SpravRates({ initialCurrencyRates, initialVatRates }: Props) {
  const today = new Date().toISOString().slice(0, 10);

  const currencies = [...new Set(initialCurrencyRates.map((r) => r.currency_code))];
  const tabs = [...currencies, "НДС"];

  const [activeTab, setActiveTab] = useState<string>(tabs[0] ?? "НДС");
  const [cRates, setCRates] = useState(initialCurrencyRates);

  const isCurTab = activeTab !== "НДС";
  const curRates = sortVersionsDesc(cRates.filter((r) => r.currency_code === activeTab));
  const vatRates = sortVersionsDesc(initialVatRates);
  const bars = computeBars(curRates, today);

  // ── Add currency version ────────────────────────────────────────────────
  const [newRate, setNewRate] = useState("");
  const [newStart, setNewStart] = useState("");
  const [addMsg, setAddMsg] = useState("");
  const [addPending, setAddPending] = useState(false);

  async function handleAddCur() {
    const rate = parseFloat(newRate);
    if (!newStart || isNaN(rate)) return;
    setAddPending(true);
    setAddMsg("");
    const ok = await addRateVersion("currency-rates", {
      currency_code: activeTab,
      rate,
      start_date: newStart,
    });
    if (ok) {
      setCRates((prev) => [
        ...prev,
        { id: -Date.now(), currency_code: activeTab, rate, start_date: newStart, end_date: null },
      ]);
      setNewRate("");
      setNewStart("");
      setAddMsg("Версия добавлена");
    } else {
      setAddMsg("Бэкенд недоступен — версия не сохранена");
    }
    setAddPending(false);
  }

  // ── As-of lookup ────────────────────────────────────────────────────────
  const [asOf, setAsOf] = useState("");
  const [asOfRes, setAsOfRes] = useState<CurrencyRateRow | null | "pending">(null);

  async function handleAsOf() {
    if (!asOf || !isCurTab) return;
    setAsOfRes("pending");
    setAsOfRes(await currencyRateAsOf(activeTab, asOf));
  }

  function switchTab(t: string) {
    setActiveTab(t);
    setAddMsg("");
    setAsOfRes(null);
  }

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      {/* Title */}
      <div>
        <h1 className="text-xl font-bold text-ink">Курсы валют и ставки НДС</h1>
        <p className="mt-1 text-sm text-muted">
          Версионные справочники (SCD Type 2) — история по датам.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 rounded-xl bg-sunken p-1">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => switchTab(t)}
            className={`flex items-center gap-1 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === t ? "bg-surface text-ink shadow-card" : "text-muted hover:text-ink"
            }`}
          >
            {t === "НДС" ? (
              <>
                <Percent className="h-3.5 w-3.5" />
                НДС
              </>
            ) : (
              <>
                <Clock className="h-3.5 w-3.5" />
                {t} → BYN
              </>
            )}
          </button>
        ))}
      </div>

      {isCurTab ? (
        <>
          {/* Header card */}
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-semibold text-ink">
                  Курс {activeTab} → BYN
                </h2>
                <Clock className="h-4 w-4 text-muted" />
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                  /refs/currency_rates
                </span>
                <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
                  версионный · SCD2
                </span>
              </div>
            </div>
            <p className="mt-3 text-[13px] text-muted">
              Эталонный курс белорусского рубля за 1 {activeTab}. Каждое изменение создаёт новую
              версию — прошлые значения сохраняются для документов прошедших дат.
            </p>
          </div>

          {/* Timeline */}
          {curRates.length > 0 ? (
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Периоды действия
              </div>
              <h3 className="mt-1 text-sm font-semibold text-ink">Таймлайн версий курса</h3>
              <div className="mt-5">
                <div className="flex items-stretch gap-1.5">
                  {bars.map(({ row, status, w }) => (
                    <div key={row.id} className="flex flex-col" style={{ width: `${w}%` }}>
                      <div className={barClass(status)}>
                        {row.rate}
                        {status !== "archived" && (
                          <span className="text-[11px] font-normal opacity-90">
                            {status === "current" ? "текущая" : "план"}
                          </span>
                        )}
                      </div>
                      <div
                        className={`mt-1.5 text-center text-[11px] ${
                          status === "current"
                            ? "font-medium text-accent-ink"
                            : status === "planned"
                              ? "text-amber-700"
                              : "text-muted"
                        }`}
                      >
                        {status === "current"
                          ? `с ${formatDate(row.start_date)} →`
                          : `${formatDate(row.start_date)} – ${formatDate(row.end_date)}`}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-5 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-muted">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-3 w-3 rounded bg-line-strong" /> архивные
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-3 w-3 rounded bg-accent" /> текущая
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block h-3 w-3 rounded border border-dashed border-amber-300 bg-amber-50" />{" "}
                    запланирована
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <div className="rounded-2xl bg-surface p-5 shadow-card text-sm text-muted">
              Данные о курсах недоступны — бэкенд не отвечает. Проверьте подключение.
            </div>
          )}

          {/* Versions table */}
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Версии
                </div>
                <h3 className="mt-1 text-sm font-semibold text-ink">
                  История значений (SCD Type 2)
                </h3>
              </div>
              <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                {curRates.length} версий
              </span>
            </div>
            <div className="mt-4 overflow-hidden rounded-xl ring-1 ring-line">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                    <th className="px-3 py-2 font-semibold">Значение, BYN/{activeTab}</th>
                    <th className="px-3 py-2 font-semibold">Действует с</th>
                    <th className="px-3 py-2 font-semibold">По</th>
                    <th className="px-3 py-2 font-semibold">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {curRates.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="px-3 py-4 text-center text-muted">
                        Нет данных
                      </td>
                    </tr>
                  ) : (
                    curRates.map((r) => {
                      const s = versionStatus(r, today);
                      const isActive = s === "current";
                      return (
                        <tr
                          key={r.id}
                          className={
                            isActive
                              ? "bg-accent-soft/30 hover:bg-accent-soft/40"
                              : "text-faint hover:bg-sunken/60"
                          }
                        >
                          <td
                            className={`px-3 py-2.5 font-mono text-[13px] ${isActive ? "font-semibold text-ink" : ""}`}
                          >
                            {r.rate}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[13px]">
                            {formatDate(r.start_date)}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[13px]">
                            {r.end_date ? (
                              formatDate(r.end_date)
                            ) : (
                              <span className="text-muted">
                                —{" "}
                                <span className="text-[11px] not-italic">(текущая)</span>
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusBadge s={s} />
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[12px] text-muted">
              Текущая версия — та, где «по» пусто (
              <span className="font-mono">end_date IS NULL</span>). Архивные строки приглушены.
            </p>
          </div>

          {/* 2-col: Add version + As-of */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Add version */}
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Новая версия
              </div>
              <h3 className="mt-1 text-sm font-semibold text-ink">Добавить значение курса</h3>
              <div className="mt-4 space-y-3">
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-muted">
                    Значение (BYN за 1 {activeTab})
                  </label>
                  <div className="rounded-xl bg-sunken px-3 py-2">
                    <input
                      type="number"
                      step="0.0001"
                      min="0"
                      className="w-full bg-transparent text-ink text-sm outline-none placeholder:text-faint"
                      placeholder="например, 3.27"
                      value={newRate}
                      onChange={(e) => setNewRate(e.target.value)}
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-muted">
                    Действует с
                  </label>
                  <div className="rounded-xl bg-sunken px-3 py-2">
                    <input
                      type="date"
                      className="w-full bg-transparent text-ink text-sm outline-none"
                      value={newStart}
                      onChange={(e) => setNewStart(e.target.value)}
                    />
                  </div>
                </div>
                <p className="text-[12px] text-muted">
                  Предыдущая версия закроется этой датой; интервал полуоткрытый{" "}
                  <span className="font-mono">[с, …)</span>.
                </p>
                <div className="flex items-center gap-3 pt-1">
                  <button
                    onClick={handleAddCur}
                    disabled={addPending || !newRate || !newStart}
                    className="flex items-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-semibold text-white shadow-card disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" /> Добавить версию
                  </button>
                  {addMsg && (
                    <span
                      className={`text-[12px] ${addMsg.includes("добавлена") ? "text-emerald-700" : "text-red-600"}`}
                    >
                      {addMsg}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* As-of lookup */}
            <div className="rounded-2xl bg-surface p-5 shadow-card">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                Предпросмотр на дату
              </div>
              <h3 className="mt-1 text-sm font-semibold text-ink">
                Какой курс увидит документ
              </h3>
              <div className="mt-4 space-y-3">
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-muted">
                    Дата документа
                  </label>
                  <div className="flex gap-2">
                    <div className="flex-1 rounded-xl bg-sunken px-3 py-2">
                      <input
                        type="date"
                        className="w-full bg-transparent text-ink text-sm outline-none"
                        value={asOf}
                        onChange={(e) => {
                          setAsOf(e.target.value);
                          setAsOfRes(null);
                        }}
                      />
                    </div>
                    <button
                      onClick={handleAsOf}
                      disabled={!asOf || asOfRes === "pending"}
                      className="rounded-xl bg-sunken px-3 py-2 text-ink hover:bg-sunken disabled:opacity-50"
                      title="Найти курс"
                    >
                      <CalendarDays className="h-4 w-4" />
                    </button>
                  </div>
                </div>

                {asOfRes === "pending" && (
                  <div className="rounded-xl bg-sunken px-4 py-3 text-sm text-muted">
                    Запрос…
                  </div>
                )}
                {asOfRes !== null && asOfRes !== "pending" &&
                  (asOfRes ? (
                    <div className="rounded-xl bg-emerald-50 px-4 py-3 ring-1 ring-emerald-100">
                      <div className="text-[12px] text-emerald-700">
                        Документ на эту дату видит курс
                      </div>
                      <div className="mt-0.5 text-lg font-bold text-emerald-700">
                        {asOfRes.rate}{" "}
                        <span className="text-sm font-medium">BYN/{activeTab}</span>
                      </div>
                      <div className="mt-0.5 text-[11px] text-emerald-700/80">
                        версия действовала {formatDate(asOfRes.start_date)} –{" "}
                        {formatDate(asOfRes.end_date)} (по не включительно)
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-xl bg-sunken px-4 py-3 text-sm text-muted">
                      Курс на указанную дату не найден.
                    </div>
                  ))}
              </div>
            </div>
          </div>

          {/* Dark SQL card */}
          <div className="rounded-2xl bg-ink p-5 text-slate-300 shadow-card">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              Как берётся курс на дату (structured)
            </div>
            <p className="mt-2 text-[13px] text-slate-400">
              AI и документы получают точное значение структурным запросом — не через эмбеддинги.
              Полуоткрытый интервал гарантирует ровно одну версию на любую дату.
            </p>
            <pre className="mt-3 rounded-xl bg-black/30 p-3 text-[12px] leading-relaxed text-slate-200">
              {`SELECT rate
FROM   public.currency_rates
WHERE  base = '${activeTab}' AND quote = 'BYN'
  AND  valid_from <= :doc_date
  AND  (valid_to IS NULL OR :doc_date < valid_to)
LIMIT  1;`}
            </pre>
          </div>
        </>
      ) : (
        /* ── VAT tab ────────────────────────────────────────────────────────── */
        <>
          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex items-center gap-2">
              <h2 className="text-base font-semibold text-ink">
                Ставки НДС — история по датам
              </h2>
              <Clock className="h-4 w-4 text-muted" />
              <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
                версионный · SCD2
              </span>
            </div>
            <p className="mt-2 text-[13px] text-muted">
              Ставки НДС версионируются (SCD Type 2). Документ видит ставку,
              действовавшую на свою дату.
            </p>
          </div>

          <div className="rounded-2xl bg-surface p-5 shadow-card">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
                  Версии
                </div>
                <h3 className="mt-1 text-sm font-semibold text-ink">
                  История ставок НДС (SCD Type 2)
                </h3>
              </div>
              <span className="rounded-full bg-sunken px-2 py-0.5 text-[11px] text-muted">
                {vatRates.length} версий
              </span>
            </div>
            <div className="mt-4 overflow-hidden rounded-xl ring-1 ring-line">
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="border-y border-line bg-sunken/60 text-left text-[11px] uppercase tracking-wide text-faint">
                    <th className="px-3 py-2 font-semibold">Код</th>
                    <th className="px-3 py-2 font-semibold">Наименование</th>
                    <th className="px-3 py-2 font-semibold">Ставка, %</th>
                    <th className="px-3 py-2 font-semibold">Действует с</th>
                    <th className="px-3 py-2 font-semibold">По</th>
                    <th className="px-3 py-2 font-semibold">Статус</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {vatRates.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-3 py-4 text-center text-muted">
                        Нет данных
                      </td>
                    </tr>
                  ) : (
                    vatRates.map((r) => {
                      const s = versionStatus(r, today);
                      const isActive = s === "current";
                      return (
                        <tr
                          key={r.id}
                          className={
                            isActive
                              ? "bg-accent-soft/30 hover:bg-accent-soft/40"
                              : "text-faint hover:bg-sunken/60"
                          }
                        >
                          <td className="px-3 py-2.5 font-mono text-[13px]">{r.code}</td>
                          <td
                            className={`px-3 py-2.5 text-[13px] ${isActive ? "font-semibold text-ink" : ""}`}
                          >
                            {r.title}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[13px]">{r.rate}%</td>
                          <td className="px-3 py-2.5 font-mono text-[13px]">
                            {formatDate(r.start_date)}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[13px]">
                            {r.end_date ? (
                              formatDate(r.end_date)
                            ) : (
                              <span className="text-muted">
                                — <span className="text-[11px]">(текущая)</span>
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2.5">
                            <StatusBadge s={s} />
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* SCD2 explanation (always visible) */}
      <div className="rounded-2xl bg-surface p-5 shadow-card">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-faint">
          Как это устроено
        </div>
        <ul className="mt-2 space-y-1.5 text-[13px] text-muted">
          <li className="flex gap-2">
            <Clock className="mt-0.5 h-4 w-4 flex-shrink-0 text-faint" />
            <span>
              Текущая версия = «по» пусто (
              <span className="font-mono">end_date IS NULL</span>); прошлые не
              перезаписываются, а закрываются датой начала следующей.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 flex-shrink-0 text-faint">◷</span>
            <span>
              Интервал полуоткрытый{" "}
              <span className="font-mono">[действует с, по)</span> — дата «по» в период
              не входит, версии стыкуются без перекрытий и зазоров.
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 flex-shrink-0 text-faint">🗃</span>
            <span>
              SCD Type 2 ведётся вручную (сервис-слой), т.к. стек — PostgreSQL 16;
              нативные temporal-таблицы появятся в PG18/19.
            </span>
          </li>
        </ul>
      </div>
    </div>
  );
}
