"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Card, Caption } from "@/components/rop/ui";
import { formatByn } from "@/lib/format";

/**
 * Скорборд план/факт показателей за период (день по умолчанию) — менеджер/РОП.
 *
 * Реальный бэк `/sales/kpis?period=…` (KpiTarget × Activity, sales-34): факт — сумма
 * активностей в окне периода, план — дневная цель × рабочие дни. Деньги (unit="money")
 * форматируются в BYN; счётные — числом. GET и POST ведут независимые состояния:
 * ошибка/пустой список не смешиваются, а неподтверждённый POST удерживает блокировку.
 */
type Row = {
  key: string;
  title: string;
  target: number;
  actual: number;
  percent: number;
  unit: "count" | "money";
};

type Context = { period: string };
type ListState = {
  context: Context;
  status: "loading" | "error" | "ready";
  rows: Row[];
  hasSnapshot: boolean;
  stale: boolean;
  error: string;
};
type ListRequest = { context: Context; controller: AbortController };
type WriteState = {
  kind: "idle" | "pending" | "rejected" | "unknown" | "confirmed";
  message: string;
};

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

function fmtValue(v: number, unit: Row["unit"]): string {
  return unit === "money" ? formatByn(v) : new Intl.NumberFormat("ru-RU").format(Math.round(v));
}

function parseRows(value: unknown): Row[] | null {
  if (!Array.isArray(value)) return null;

  const rows: Row[] = [];
  const keys = new Set<string>();
  for (const candidate of value) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) return null;
    const row = candidate as Record<string, unknown>;
    if (
      typeof row.key !== "string" || !row.key.trim()
      || typeof row.title !== "string" || !row.title.trim()
      || typeof row.target !== "number" || !Number.isFinite(row.target)
      || typeof row.actual !== "number" || !Number.isFinite(row.actual)
      || typeof row.percent !== "number" || !Number.isFinite(row.percent)
      || (row.unit !== "count" && row.unit !== "money")
      || keys.has(row.key)
    ) return null;

    keys.add(row.key);
    rows.push({
      key: row.key,
      title: row.title,
      target: row.target,
      actual: row.actual,
      percent: row.percent,
      unit: row.unit,
    });
  }
  return rows;
}

function listFailure(cause: unknown): string {
  if (cause instanceof Error && cause.message.startsWith("HTTP ")) {
    return `Не удалось загрузить показатели (${cause.message}).`;
  }
  if ((cause instanceof Error && cause.message === "INVALID_LIST") || cause instanceof SyntaxError) {
    return "Сервер вернул некорректный список показателей.";
  }
  return "Не удалось загрузить показатели. Проверьте соединение и повторите попытку.";
}

function isValidDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  if (Number(value.slice(0, 4)) < 1) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isConfirmedReceipt(value: unknown): value is { ok: true; date: string } {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const receipt = value as Record<string, unknown>;
  return Object.keys(receipt).length === 2
    && Object.prototype.hasOwnProperty.call(receipt, "ok")
    && Object.prototype.hasOwnProperty.call(receipt, "date")
    && receipt.ok === true
    && isValidDate(receipt.date);
}

export function DayScoreboard() {
  const [period, setPeriod] = useState("day");
  // Object identity distinguishes A → B → A, even though the URL repeats.
  const context = useMemo(() => ({ period }), [period]);
  const [listState, setListState] = useState<ListState>(() => ({
    context,
    status: "loading",
    rows: [],
    hasSnapshot: false,
    stale: false,
    error: "",
  }));
  const [writeState, setWriteState] = useState<WriteState>({ kind: "idle", message: "" });

  const currentContext = useRef<Context | null>(null);
  const activeListRequest = useRef<ListRequest | null>(null);
  const writeLock = useRef<object | null>(null);

  useLayoutEffect(() => {
    currentContext.current = context;
    return () => {
      if (currentContext.current === context) currentContext.current = null;
      const active = activeListRequest.current;
      if (active?.context === context) {
        active.controller.abort();
        if (activeListRequest.current === active) activeListRequest.current = null;
      }
    };
  }, [context]);

  const loadRows = useCallback(async (requestContext: Context, preserveSnapshot: boolean): Promise<boolean> => {
    if (currentContext.current !== requestContext) return false;

    activeListRequest.current?.controller.abort();
    const request: ListRequest = { context: requestContext, controller: new AbortController() };
    activeListRequest.current = request;
    setListState((previous) => {
      const sameContext = previous.context === requestContext;
      const keepSnapshot = preserveSnapshot && sameContext && previous.hasSnapshot;
      return {
        context: requestContext,
        status: "loading",
        rows: keepSnapshot ? previous.rows : [],
        hasSnapshot: keepSnapshot,
        stale: keepSnapshot,
        error: "",
      };
    });

    const isCurrent = () => currentContext.current === requestContext
      && activeListRequest.current === request
      && !request.controller.signal.aborted;

    try {
      const response = await fetch(`/api/sales/kpis?period=${encodeURIComponent(requestContext.period)}`, {
        cache: "no-store",
        signal: request.controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      const payload: unknown = await response.json();
      if (!isCurrent()) return false;
      const rows = parseRows(payload);
      if (!rows) throw new Error("INVALID_LIST");

      setListState({
        context: requestContext,
        status: "ready",
        rows,
        hasSnapshot: true,
        stale: false,
        error: "",
      });
      return true;
    } catch (cause) {
      if (!isCurrent()) return false;
      setListState((previous) => {
        const sameContext = previous.context === requestContext;
        const hasSnapshot = sameContext && previous.hasSnapshot;
        return {
          context: requestContext,
          status: "error",
          rows: hasSnapshot ? previous.rows : [],
          hasSnapshot,
          stale: hasSnapshot,
          error: listFailure(cause),
        };
      });
      return false;
    } finally {
      if (activeListRequest.current === request) activeListRequest.current = null;
    }
  }, []);

  useEffect(() => {
    void loadRows(context, false);
    return () => {
      const active = activeListRequest.current;
      if (active?.context === context) {
        active.controller.abort();
        if (activeListRequest.current === active) activeListRequest.current = null;
      }
    };
  }, [context, loadRows]);

  const matchingList = listState.context === context;
  const rows = matchingList ? listState.rows : [];
  const status = matchingList ? listState.status : "loading";
  const hasSnapshot = matchingList && listState.hasSnapshot;
  const stale = matchingList && listState.stale;
  const listErrorMessage = matchingList ? listState.error : "";
  const writeLocked = writeLock.current !== null;
  const canWrite = hasSnapshot && status === "ready" && !stale && !writeLocked;

  async function bump(key: string) {
    if (!canWrite || writeLock.current !== null || currentContext.current === null) return;

    const lock = {};
    writeLock.current = lock;
    setWriteState({ kind: "pending", message: "Отправляем отметку активности…" });
    let retainLock = false;
    let confirmedReceiptDate: string | null = null;
    const markUnknown = (reason: string) => {
      retainLock = true;
      setWriteState({
        kind: "unknown",
        message: `Результат отметки не подтверждён (${reason}). Повторная отправка заблокирована; проверьте результат вручную.`,
      });
    };

    try {
      const response = await fetch("/api/sales/activities", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kpi_key: key, value: 1 }),
      });

      if (currentContext.current === null) return;
      if ([401, 403, 422].includes(response.status)) {
        setWriteState({
          kind: "rejected",
          message: `Отметка отклонена сервером (HTTP ${response.status}). После проверки можно повторить вручную.`,
        });
        return;
      }

      if (response.status !== 201) {
        markUnknown(`HTTP ${response.status}`);
        return;
      }

      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        if (currentContext.current !== null) markUnknown("некорректный ответ");
        return;
      }
      if (currentContext.current === null) return;
      if (!isConfirmedReceipt(payload)) {
        markUnknown("ответ не содержит подтверждённую дату");
        return;
      }

      const receiptDate = payload.date;
      confirmedReceiptDate = receiptDate;
      setWriteState({ kind: "confirmed", message: `Отметка подтверждена за ${receiptDate}.` });
      const refreshContext = currentContext.current;
      if (refreshContext !== null) {
        await loadRows(refreshContext, true);
      }
    } catch {
      if (currentContext.current !== null) markUnknown("нет ответа от сервера");
    } finally {
      if (writeLock.current === lock && !retainLock) {
        writeLock.current = null;
        if (currentContext.current !== null && confirmedReceiptDate !== null) {
          setWriteState({ kind: "confirmed", message: `Отметка подтверждена за ${confirmedReceiptDate}.` });
        }
      }
    }
  }

  const done = rows.filter((row) => row.percent >= 100).length;
  const summary = hasSnapshot
    ? rows.length > 0
      ? `${done}/${rows.length} закрыто`
      : status === "ready" ? "показатели" : "последний список был пуст"
    : status === "error" ? "данные недоступны" : "показатели";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Caption>План / факт · {summary} · валюта BYN</Caption>
        <div className="flex items-center gap-1 rounded-lg border border-line p-0.5">
          {PERIODS.map((item) => (
            <button
              key={item.id}
              onClick={() => setPeriod(item.id)}
              className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                period === item.id ? "bg-accent text-white" : "text-muted hover:text-ink"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {writeState.kind === "pending" && (
        <p className="text-sm text-muted" role="status">{writeState.message}</p>
      )}
      {writeState.kind === "rejected" && (
        <p className="text-sm text-danger" role="alert">{writeState.message}</p>
      )}
      {writeState.kind === "unknown" && (
        <p className="text-sm text-danger" role="alert">{writeState.message}</p>
      )}
      {writeState.kind === "confirmed" && (
        <p className="text-sm text-muted" role="status">{writeState.message}</p>
      )}

      {status === "loading" && !hasSnapshot && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Card key={index} className="h-[92px] animate-pulse bg-sunken">
              <span className="sr-only">загрузка</span>
            </Card>
          ))}
        </div>
      )}

      {status === "loading" && hasSnapshot && (
        <Card className="text-sm text-muted">
          <span role="status">
            Обновляем показатели; показан предыдущий срез, запись временно заблокирована.
          </span>
        </Card>
      )}

      {status === "error" && (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-danger" role="alert">
            {listErrorMessage}{stale
              ? " Показан предыдущий срез; запись заблокирована до успешного обновления."
              : " Данные недоступны, поэтому пустой список не подтверждён."}
          </span>
          <button
            onClick={() => void loadRows(context, true)}
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

      {status === "error" && hasSnapshot && rows.length === 0 && (
        <Card className="text-sm text-muted">Последний успешно загруженный список был пустым.</Card>
      )}

      {hasSnapshot && rows.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((row) => {
            const tone = toneClasses(row.percent);
            return (
              <Card key={row.key} className="!p-4">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[12.5px] font-medium leading-tight text-ink">{row.title}</div>
                  {row.unit === "count" && (
                    <button
                      onClick={() => void bump(row.key)}
                      disabled={!canWrite}
                      title="Отметить +1 факт"
                      className="shrink-0 rounded-md border border-line px-2 py-0.5 text-xs font-semibold text-muted hover:text-ink disabled:opacity-50"
                    >
                      +1
                    </button>
                  )}
                </div>
                <div className="mt-2 flex items-baseline gap-1.5">
                  <span className={`text-lg font-bold tabular-nums ${tone.text}`}>
                    {fmtValue(row.actual, row.unit)}
                  </span>
                  <span className="text-xs text-muted">/ {fmtValue(row.target, row.unit)}</span>
                </div>
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-sunken">
                  <div className={`h-full ${tone.bar}`} style={{ width: `${Math.min(100, row.percent)}%` }} />
                </div>
                <div className={`mt-1 text-right text-[11px] font-semibold ${tone.text}`}>{row.percent}%</div>
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
