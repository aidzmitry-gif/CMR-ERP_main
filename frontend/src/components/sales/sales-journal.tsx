"use client";

import { Banknote, ClipboardList, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { formatByn } from "@/lib/format";
import {
  EMPTY_JOURNAL_FILTERS,
  filterJournal,
  formatDayMonth,
  funnelLabel,
  journalStats,
  monthGroups,
  type JournalFilters,
  type JournalRow,
  type PaymentStatus,
  type ShipmentStatus,
} from "@/lib/sales-journal";

type Status = "loading" | "error" | "ready";

const SELECT_CLS =
  "rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[12.5px] text-muted focus:border-accent focus:outline-none";

const CHIP_CLS =
  "rounded-md border border-line bg-surface px-2 py-1 text-[11px] font-semibold text-muted hover:border-accent hover:bg-accent-soft hover:text-accent-ink";

const PAYMENT_CLS: Record<PaymentStatus, string> = {
  paid: "bg-emerald-50 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300",
  invoiced: "bg-amber-50 text-amber-600 dark:bg-amber-500/15 dark:text-amber-300",
  none: "bg-sunken text-muted",
};

const PAYMENT_LABEL: Record<PaymentStatus, string> = {
  paid: "оплачен",
  invoiced: "счёт выставлен",
  none: "нет счёта",
};

const SHIPMENT_CLS: Record<ShipmentStatus, string> = {
  delivered: "bg-blue-50 text-blue-600 dark:bg-blue-500/15 dark:text-blue-300",
  none: "bg-sunken text-faint",
};

const SHIPMENT_LABEL: Record<ShipmentStatus, string> = {
  delivered: "доставлено",
  none: "—",
};

// быстрый период от реального «сегодня» — последние N дней включительно
function quickRange(days: number): { from: string; to: string } {
  const today = new Date();
  const past = new Date(today);
  past.setDate(today.getDate() - days + 1);
  const iso = (dt: Date) =>
    `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
  return { from: iso(past), to: iso(today) };
}

export function SalesJournal() {
  const [status, setStatus] = useState<Status>("loading");
  const [rows, setRows] = useState<JournalRow[]>([]);
  const [filters, setFilters] = useState<JournalFilters>(EMPTY_JOURNAL_FILTERS);

  // фетч один раз на маунт; ignore-флаг — гейт от записи в размонтированный компонент
  useEffect(() => {
    let ignore = false;
    fetch("/api/sales/journal", { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json() as Promise<JournalRow[]>;
      })
      .then((data) => {
        if (!ignore) {
          setRows(data);
          setStatus("ready");
        }
      })
      .catch(() => {
        if (!ignore) setStatus("error");
      });
    return () => {
      ignore = true;
    };
  }, []);

  function patchFilter<K extends keyof JournalFilters>(key: K, value: JournalFilters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  function resetFilters() {
    setFilters(EMPTY_JOURNAL_FILTERS);
  }

  function applyQuickDate(days: number) {
    if (!days) {
      setFilters((f) => ({ ...f, from: "", to: "" }));
      return;
    }
    const { from, to } = quickRange(days);
    setFilters((f) => ({ ...f, from, to }));
  }

  const options = useMemo(() => {
    const uniq = (arr: string[]) => [...new Set(arr)].sort();
    return { funnel: uniq(rows.map((r) => r.funnel)), owner: uniq(rows.map((r) => r.owner)) };
  }, [rows]);

  const filtered = useMemo(() => filterJournal(rows, filters), [rows, filters]);
  const stats = useMemo(() => journalStats(filtered), [filtered]);
  const groups = useMemo(() => monthGroups(filtered), [filtered]);

  // подсказка для карточки маржи, когда в срезе нет ни одной оценённой сделки
  const firstMarginReason = useMemo(
    () => filtered.find((r) => r.gross_profit == null && r.margin_reason)?.margin_reason ?? null,
    [filtered],
  );

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="mx-auto max-w-[1220px] space-y-4">
        {/* Заголовок */}
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-ink">
            <ClipboardList size={20} className="text-accent" /> Журнал продаж
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Реестр свершившихся продаж: сделка попадает сюда в момент «Выиграна».
          </p>
        </div>

        {status === "error" && (
          <div className="rounded-2xl border border-line bg-surface p-6 text-center text-sm text-muted shadow-card">
            Журнал недоступен — проверьте бэкенд
          </div>
        )}

        {status === "loading" && (
          <div className="rounded-2xl border border-line bg-surface p-6 text-center text-sm text-muted shadow-card">
            Загрузка…
          </div>
        )}

        {status === "ready" && (
          <>
            {/* Скорборд */}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
                <div className="text-xl font-bold tabular-nums text-ink">{stats.count}</div>
                <div className="mt-1 text-[11.5px] text-muted">продаж</div>
              </div>
              <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
                <div className="text-xl font-bold tabular-nums text-money">
                  {formatByn(stats.totalAmount)}
                </div>
                <div className="mt-1 text-[11.5px] text-muted">сумма</div>
              </div>
              <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
                {stats.totalGross != null ? (
                  <div className="text-xl font-bold tabular-nums text-money">
                    {formatByn(stats.totalGross)}
                  </div>
                ) : (
                  <div
                    className="text-xl font-bold tabular-nums text-faint"
                    title={firstMarginReason ?? undefined}
                  >
                    —
                  </div>
                )}
                <div className="mt-1 text-[11.5px] text-muted">
                  валовая прибыль · по {stats.pricedCount} из {stats.count} оценённых
                </div>
              </div>
              <div className="rounded-2xl border border-line bg-surface p-4 shadow-card">
                <div className="flex items-center gap-1.5 text-xl font-bold tabular-nums text-amber-600 dark:text-amber-300">
                  <Banknote size={16} /> {stats.unpaidCount}
                </div>
                <div className="mt-1 text-[11.5px] text-muted">неоплаченных</div>
              </div>
            </div>

            {/* Фильтры */}
            <div className="flex flex-wrap items-center gap-2.5 rounded-2xl border border-line bg-surface p-3 shadow-card">
              <span className="flex items-center gap-1.5 text-[11px] text-muted">
                Период
                <input
                  type="date"
                  value={filters.from}
                  onChange={(e) => patchFilter("from", e.target.value)}
                  title="дата с"
                  className={SELECT_CLS}
                />
                <span className="text-muted">–</span>
                <input
                  type="date"
                  value={filters.to}
                  onChange={(e) => patchFilter("to", e.target.value)}
                  title="дата по"
                  className={SELECT_CLS}
                />
              </span>

              <span className="flex gap-1">
                <button type="button" onClick={() => applyQuickDate(7)} className={CHIP_CLS}>
                  7 дн
                </button>
                <button type="button" onClick={() => applyQuickDate(30)} className={CHIP_CLS}>
                  30 дн
                </button>
                <button type="button" onClick={() => applyQuickDate(0)} className={CHIP_CLS}>
                  сброс
                </button>
              </span>

              <label className="flex items-center gap-1.5 text-[11px] text-muted">
                Воронка
                <select
                  value={filters.funnel}
                  onChange={(e) => patchFilter("funnel", e.target.value)}
                  className={SELECT_CLS}
                >
                  <option value="">Все воронки</option>
                  {options.funnel.map((code) => (
                    <option key={code} value={code}>
                      {funnelLabel(code)}
                    </option>
                  ))}
                </select>
              </label>

              <label className="flex items-center gap-1.5 text-[11px] text-muted">
                Менеджер
                <select
                  value={filters.owner}
                  onChange={(e) => patchFilter("owner", e.target.value)}
                  className={SELECT_CLS}
                >
                  <option value="">Все менеджеры</option>
                  {options.owner.map((owner) => (
                    <option key={owner} value={owner}>
                      {owner}
                    </option>
                  ))}
                </select>
              </label>

              <label className="relative flex items-center">
                <Search size={14} className="pointer-events-none absolute left-2.5 text-faint" />
                <input
                  type="search"
                  value={filters.q}
                  onChange={(e) => patchFilter("q", e.target.value)}
                  placeholder="номер / название / клиент"
                  className="rounded-lg border border-line bg-surface py-1.5 pl-8 pr-2.5 text-[12.5px] text-ink placeholder:text-faint focus:border-accent focus:outline-none"
                />
              </label>

              <label className="flex cursor-pointer select-none items-center gap-1.5 text-[12.5px] text-amber-600 dark:text-amber-300">
                <input
                  type="checkbox"
                  checked={filters.unpaidOnly}
                  onChange={(e) => patchFilter("unpaidOnly", e.target.checked)}
                  className="accent-amber-500"
                />
                только неоплаченные
              </label>

              <button
                type="button"
                onClick={resetFilters}
                title="Сбросить все фильтры"
                className="ml-auto inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-[11.5px] font-semibold text-muted hover:bg-sunken"
              >
                Сбросить
              </button>
            </div>

            {/* Лента по месяцам */}
            {groups.length === 0 ? (
              <div className="rounded-2xl border border-line bg-surface p-10 text-center text-sm shadow-card">
                {rows.length === 0 ? (
                  <span className="text-faint">
                    Продаж пока нет — журнал заполнится, когда выиграете первую сделку
                  </span>
                ) : (
                  <div className="space-y-2">
                    <span className="text-faint">Ничего не найдено</span>
                    <div>
                      <button
                        type="button"
                        onClick={resetFilters}
                        className="font-semibold text-accent-ink hover:text-accent"
                      >
                        Сбросить фильтры
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ) : (
              groups.map((g) => (
                <div
                  key={g.key}
                  className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card"
                >
                  <div className="flex items-center gap-2.5 border-b border-line bg-sunken px-4 py-3">
                    <span className="text-sm font-semibold text-ink">{g.title}</span>
                    <span className="rounded-full bg-surface px-2.5 py-0.5 text-[11px] font-semibold text-muted">
                      {g.rows.length}
                    </span>
                    <span className="ml-auto text-xs tabular-nums text-muted">
                      {formatByn(g.sum)}
                    </span>
                  </div>

                  {g.rows.map((row) => (
                    <JournalRowView key={row.deal_id} row={row} />
                  ))}
                </div>
              ))
            )}
          </>
        )}
      </div>
    </main>
  );
}

function JournalRowView({ row }: { row: JournalRow }) {
  const priced = row.gross_profit != null && row.margin_pct != null;
  return (
    <div className="grid grid-cols-[84px_1fr_130px_120px_120px_110px_130px_120px_92px] items-center gap-3 border-b border-line px-4 py-3 last:border-0">
      <div className="text-[13px] font-bold tabular-nums text-ink">
        {formatDayMonth(row.closed_on)}
      </div>

      <div className="min-w-0">
        <div className="truncate text-[13px] text-ink">
          <b className="font-semibold">{row.number}</b> · {row.title}
        </div>
      </div>

      <div className="truncate text-[12.5px] text-muted">{row.counterparty}</div>
      <div className="truncate text-[12.5px] text-muted">{row.owner}</div>

      <span className="w-fit whitespace-nowrap rounded-md bg-sunken px-2 py-1 text-[11px] font-semibold text-muted">
        {funnelLabel(row.funnel)}
      </span>

      <div className="text-right text-[13px] font-semibold tabular-nums text-money">
        {formatByn(row.amount)}
      </div>

      {priced ? (
        <span className="w-fit whitespace-nowrap rounded-md bg-emerald-50 px-2 py-0.5 text-[11px] font-bold text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
          {Math.round(row.margin_pct as number)}% · {formatByn(row.gross_profit as number)}
        </span>
      ) : (
        <span
          className="text-[12px] text-faint"
          title={row.margin_reason ?? "маржа не рассчитана"}
        >
          —
        </span>
      )}

      <span
        className={`w-fit whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-bold ${PAYMENT_CLS[row.payment]}`}
      >
        {PAYMENT_LABEL[row.payment]}
        {row.payment === "invoiced" && row.invoice_number ? ` · ${row.invoice_number}` : ""}
      </span>

      <span
        className={`w-fit whitespace-nowrap rounded-md px-2 py-0.5 text-[10px] font-bold ${SHIPMENT_CLS[row.shipment]}`}
      >
        {SHIPMENT_LABEL[row.shipment]}
      </span>
    </div>
  );
}
