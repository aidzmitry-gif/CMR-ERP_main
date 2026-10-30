"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card, Caption } from "@/components/rop/ui";
import { formatByn } from "@/lib/format";

/**
 * Скорборд план/факт показателей за период (день по умолчанию) — менеджер/РОП.
 *
 * Реальный бэк `/sales/kpis?period=…` (KpiTarget × Activity, sales-34): факт — сумма
 * активностей в окне периода, план — дневная цель × рабочие дни. Деньги (unit="money")
 * форматируются в BYN; счётные — числом. Состояния: загрузка / ошибка+повтор / honest-empty
 * (план не задан) / данные. Кнопка «+1» отмечает факт активности (POST /activities) и
 * перечитывает (только счётные метрики). Прямой fetch (а не getKpis) — чтобы различать
 * «ошибка» и «пусто» (getKpis глушит ошибку в []).
 */
type Row = {
  key: string;
  title: string;
  target: number;
  actual: number;
  percent: number;
  unit: string; // "count" | "money"
};

type Status = "loading" | "error" | "ready";

const PERIODS: { id: string; label: string }[] = [
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
];

function toneClasses(percent: number): { text: string; bar: string } {
  if (percent >= 90) return { text: "text-emerald-600", bar: "bg-emerald-500" };
  if (percent >= 50) return { text: "text-amber-600", bar: "bg-amber-500" };
  return { text: "text-red-600", bar: "bg-red-500" };
}

function fmtValue(v: number, unit: string): string {
  return unit === "money" ? formatByn(v) : new Intl.NumberFormat("ru-RU").format(Math.round(v));
}

export function DayScoreboard() {
  const [period, setPeriod] = useState("day");
  const [status, setStatus] = useState<Status>("loading");
  const [rows, setRows] = useState<Row[]>([]);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [writeIssue, setWriteIssue] = useState<{ message: string; unknown: boolean } | null>(null);
  const [reviewReady, setReviewReady] = useState(false);
  const writeLock = useRef(false);
  const unknownWrite = useRef(false);
  const currentPeriod = useRef("day");
  const readVersion = useRef(0);
  const mounted = useRef(false);

  const load = useCallback(async (p: string): Promise<boolean> => {
    const version = ++readVersion.current;
    try {
      const res = await fetch(`/api/sales/kpis?period=${encodeURIComponent(p)}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      const data: unknown = await res.json();
      if (!Array.isArray(data)) throw new Error("Invalid KPI response");
      if (!mounted.current || version !== readVersion.current || p !== currentPeriod.current) return false;
      setRows(data as Row[]);
      setStatus("ready");
      return true;
    } catch {
      if (mounted.current && version === readVersion.current && p === currentPeriod.current) {
        setRows([]);
        setStatus("error");
      }
      return false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void load(period);
    });
    return () => {
      cancelled = true;
      mounted.current = false;
    };
  }, [period, load]);

  function refresh(p: string) {
    setRows([]);
    setStatus("loading");
    return load(p);
  }

  async function retryRead() {
    if (!(await refresh(currentPeriod.current))) return;
    if (unknownWrite.current) setReviewReady(true);
    else setWriteIssue(null);
  }

  function changePeriod(p: string) {
    if (writeLock.current || p === currentPeriod.current) return;
    currentPeriod.current = p;
    ++readVersion.current;
    setReviewReady(false);
    setRows([]);
    setStatus("loading");
    setPeriod(p);
  }

  function markUnknown() {
    unknownWrite.current = true;
    setReviewReady(false);
    setWriteIssue({
      unknown: true,
      message: "Не удалось подтвердить запись активности. Она могла сохраниться. Обновите показатели и проверьте факт перед повторным добавлением.",
    });
  }

  async function reviewUnknown() {
    setReviewReady(false);
    if (await refresh(currentPeriod.current)) setReviewReady(true);
  }

  function confirmReview() {
    if (!reviewReady || !unknownWrite.current) return;
    unknownWrite.current = false;
    setReviewReady(false);
    setWriteIssue(null);
  }

  async function bump(key: string) {
    if (writeLock.current || unknownWrite.current) return;
    writeLock.current = true;
    setBusyKey(key);
    setWriteIssue(null);
    try {
      const response = await fetch("/api/sales/activities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kpi_key: key, value: 1 }),
      });
      if (!mounted.current) return;
      if (!response.ok) {
        if (response.status >= 500 || response.status === 408) {
          markUnknown();
        } else {
          setWriteIssue({
            unknown: false,
            message: response.status === 401
              ? "Сессия истекла. Войдите в ERP снова."
              : response.status === 403
                ? "Нет доступа к записи активности."
                : "Сервер отклонил запись активности. Факт не изменён.",
          });
          if (response.status === 401 || response.status === 403) {
            setRows([]);
            setStatus("error");
          }
        }
        return;
      }
      const result: unknown = await response.json();
      if (!mounted.current) return;
      if (!result || typeof result !== "object" || !("ok" in result) || result.ok !== true ||
          !("date" in result) || typeof result.date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(result.date)) {
        markUnknown();
        return;
      }
      if (!(await refresh(currentPeriod.current)) && mounted.current) {
        setWriteIssue({ unknown: false, message: "Активность записана, но не удалось обновить показатели. Нажмите «Повторить», чтобы перечитать их." });
      }
    } catch {
      if (mounted.current) markUnknown();
    } finally {
      writeLock.current = false;
      if (mounted.current) setBusyKey(null);
    }
  }

  const done = rows.filter((r) => r.percent >= 100).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Caption>
          План / факт · {rows.length ? `${done}/${rows.length} закрыто` : "показатели"} · валюта BYN
        </Caption>
        <div className="flex items-center gap-1 rounded-lg border border-line p-0.5">
          {PERIODS.map((p) => (
            <button
              key={p.id}
              onClick={() => changePeriod(p.id)}
              disabled={busyKey !== null}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                period === p.id ? "bg-accent text-white" : "text-muted hover:text-ink"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {writeIssue && (
        <div role="alert" className="space-y-2 rounded-xl border border-line p-4 text-sm text-muted">
          <p>{writeIssue.message}</p>
          {writeIssue.unknown && (
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => void reviewUnknown()}
                disabled={status === "loading" || busyKey !== null}
                className="rounded-lg border border-line px-3 py-1.5 font-semibold disabled:opacity-50"
              >
                Обновить показатели
              </button>
              {reviewReady && (
                <button onClick={confirmReview} className="rounded-lg border border-line px-3 py-1.5 font-semibold">
                  Факт проверен
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {status === "loading" && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="h-[92px] animate-pulse bg-sunken">
              <span className="sr-only">загрузка</span>
            </Card>
          ))}
        </div>
      )}

      {status === "error" && (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-muted">Не удалось загрузить показатели.</span>
          <button
            onClick={() => void retryRead()}
            className="rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white"
          >
            Повторить
          </button>
        </Card>
      )}

      {status === "ready" && rows.length === 0 && (
        <Card className="text-sm text-muted">
          Плановые показатели не заданы. Заведите цели KPI (KpiTarget) — и здесь появится план/факт дня.
        </Card>
      )}

      {status === "ready" && rows.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((r) => {
            const tone = toneClasses(r.percent);
            return (
              <Card key={r.key} className="!p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[12.5px] font-medium leading-tight text-ink">{r.title}</div>
                  {r.unit !== "money" && (
                    <button
                      onClick={() => void bump(r.key)}
                      disabled={busyKey !== null || writeIssue?.unknown === true}
                      title="Отметить +1 факт"
                      className="shrink-0 rounded-md border border-line px-2 py-0.5 text-xs font-semibold text-muted hover:text-ink disabled:opacity-50"
                    >
                      +1
                    </button>
                  )}
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className={`text-lg font-bold tabular-nums ${tone.text}`}>
                    {fmtValue(r.actual, r.unit)}
                  </span>
                  <span className="text-xs text-muted">/ {fmtValue(r.target, r.unit)}</span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-sunken">
                  <div className={`h-full ${tone.bar}`} style={{ width: `${Math.min(100, r.percent)}%` }} />
                </div>
                <div className={`mt-1 text-right text-[11px] font-semibold ${tone.text}`}>{r.percent}%</div>
              </Card>
            );
          })}
        </div>
      )}

      <p className="text-xs text-faint">
        Факт — сумма активностей за окно периода; план — дневная цель × рабочие дни (sales-34).
      </p>
    </div>
  );
}
