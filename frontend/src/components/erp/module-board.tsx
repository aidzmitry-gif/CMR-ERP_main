"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

export interface ColumnDef {
  key: string;
  label: string;
}

export interface FieldDef {
  key: string;
  label: string;
  type?: "text" | "number";
  default?: string | number;
}

type Row = Record<string, unknown>;
type Context = { endpoint: string };
type ListState = {
  context: Context;
  rows: Row[];
  loading: boolean;
  stale: boolean;
  error: string;
};
type FormState = {
  context: Context;
  values: Record<string, string | number>;
  open: boolean;
};
type WriteState = {
  context: Context;
  busy: boolean;
  outcomeUnknown: boolean;
  error: string;
  notice: string;
};
type ListRequest = {
  context: Context;
  controller: AbortController;
};
type WriteLock = { context: Context };

function blankForm(fields: FieldDef[]): Record<string, string | number> {
  return Object.fromEntries(
    fields.map((field) => [field.key, field.default ?? (field.type === "number" ? 0 : "")]),
  );
}

function isRecord(value: unknown): value is Row {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isCellValue(value: unknown): boolean {
  return value === null || value === undefined || typeof value === "string"
    || typeof value === "boolean"
    || (typeof value === "number" && Number.isFinite(value));
}

function isValidRow(value: unknown, columns: ColumnDef[]): value is Row {
  if (!isRecord(value) || !Number.isSafeInteger(value.id) || (value.id as number) <= 0) return false;
  return columns.every((column) =>
    Object.prototype.hasOwnProperty.call(value, column.key) && isCellValue(value[column.key]),
  );
}

function parseRows(value: unknown, columns: ColumnDef[]): Row[] | null {
  if (!Array.isArray(value)) return null;
  const rows: Row[] = [];
  const ids = new Set<number>();
  for (const candidate of value) {
    if (!isValidRow(candidate, columns)) return null;
    const id = candidate.id as number;
    if (ids.has(id)) return null;
    ids.add(id);
    rows.push(candidate);
  }
  return rows;
}

function listFailure(cause: unknown): string {
  if (cause instanceof Error && cause.message.startsWith("HTTP ")) {
    return "Не удалось загрузить список (" + cause.message + ").";
  }
  if (cause instanceof Error && cause.message === "INVALID_LIST") {
    return "Сервер вернул некорректный список записей.";
  }
  return "Не удалось загрузить список. Проверьте соединение и повторите попытку.";
}

function unknownWriteFailure(reason: string): string {
  return "Результат операции не подтверждён (" + reason + "). Форма сохранена; запрос автоматически не повторялся.";
}

export function ModuleBoard({
  title,
  subtitle,
  endpoint,
  columns,
  fields,
  statusKey,
  statusFlow,
  patchPath,
  action,
}: {
  title: string;
  subtitle?: string;
  endpoint: string;
  columns: ColumnDef[];
  fields: FieldDef[];
  statusKey?: string;
  statusFlow?: string[];
  patchPath?: string;
  action?: { label: string; path: string };
}) {
  // The object identity is a lifetime token: A -> B -> A is a new context even when the URL repeats.
  const context = useMemo(() => ({ endpoint }), [endpoint]);
  const [listState, setListState] = useState<ListState>(() => ({
    context,
    rows: [],
    loading: true,
    stale: false,
    error: "",
  }));
  const [formState, setFormState] = useState<FormState>(() => ({
    context,
    values: blankForm(fields),
    open: false,
  }));
  const [writeState, setWriteState] = useState<WriteState>(() => ({
    context,
    busy: false,
    outcomeUnknown: false,
    error: "",
    notice: "",
  }));

  const currentContext = useRef<Context | null>(null);
  const activeListRequest = useRef<ListRequest | null>(null);
  const writeLock = useRef<WriteLock | null>(null);

  useLayoutEffect(() => {
    currentContext.current = context;
    return () => {
      if (currentContext.current === context) currentContext.current = null;
      const active = activeListRequest.current;
      if (active?.context === context) {
        active.controller.abort();
        activeListRequest.current = null;
      }
    };
  }, [context]);

  const loadRows = useCallback(async (
    requestContext: Context,
    requestEndpoint: string,
    requestColumns: ColumnDef[],
    showStale: boolean,
  ): Promise<boolean> => {
    if (currentContext.current !== requestContext) return false;

    activeListRequest.current?.controller.abort();
    const request: ListRequest = {
      context: requestContext,
      controller: new AbortController(),
    };
    activeListRequest.current = request;

    if (showStale) {
      setListState((previous) => {
        const sameContext = previous.context === requestContext;
        const previousRows = sameContext ? previous.rows : [];
        return {
          context: requestContext,
          rows: previousRows,
          loading: true,
          stale: previousRows.length > 0,
          error: "",
        };
      });
    }

    const isCurrent = () =>
      currentContext.current === requestContext && activeListRequest.current === request;

    try {
      const response = await fetch("/api" + requestEndpoint, {
        cache: "no-store",
        signal: request.controller.signal,
      });
      if (!response.ok) throw new Error("HTTP " + response.status);

      const payload: unknown = await response.json();
      if (!isCurrent()) return false;
      const rows = parseRows(payload, requestColumns);
      if (!rows) throw new Error("INVALID_LIST");

      setListState({
        context: requestContext,
        rows,
        loading: false,
        stale: false,
        error: "",
      });
      return true;
    } catch (cause) {
      if (!isCurrent()) return false;
      setListState((previous) => {
        const previousRows = previous.context === requestContext ? previous.rows : [];
        return {
          context: requestContext,
          rows: previousRows,
          loading: false,
          stale: previousRows.length > 0,
          error: listFailure(cause),
        };
      });
      return false;
    } finally {
      if (activeListRequest.current === request) activeListRequest.current = null;
    }
  }, []);

  useEffect(() => {
    const requestContext = context;
    const requestEndpoint = endpoint;
    void loadRows(requestContext, requestEndpoint, columns, false);
    return () => {
      const active = activeListRequest.current;
      if (active?.context === requestContext) {
        active.controller.abort();
        if (activeListRequest.current === active) activeListRequest.current = null;
      }
    };
  }, [context, endpoint, columns, loadRows]);

  const matchingList = listState.context === context;
  const rows = matchingList ? listState.rows : [];
  const loading = matchingList ? listState.loading : true;
  const stale = matchingList ? listState.stale : false;
  const listError = matchingList ? listState.error : "";
  const matchingForm = formState.context === context;
  const form = matchingForm ? formState.values : blankForm(fields);
  const open = matchingForm && formState.open;
  const matchingWrite = writeState.context === context;
  const busy = matchingWrite && writeState.busy;
  const outcomeUnknown = matchingWrite && writeState.outcomeUnknown;
  const writeError = matchingWrite ? writeState.error : "";
  const writeNotice = matchingWrite ? writeState.notice : "";
  const canWrite = matchingList && !loading && !stale && !listError && !busy && !outcomeUnknown;
  const clickableStatus = Boolean(statusKey && statusFlow && statusFlow.length > 0 && patchPath);

  async function runWrite({
    requestContext,
    requestEndpoint,
    url,
    method,
    body,
    expectedId,
    expectedStatus,
    closeForm,
  }: {
    requestContext: Context;
    requestEndpoint: string;
    url: string;
    method: "POST" | "PATCH";
    body?: string;
    expectedId?: number;
    expectedStatus?: string;
    closeForm?: boolean;
  }) {
    if (!canWrite || currentContext.current !== requestContext) return;
    if (writeLock.current?.context === requestContext) return;

    const lock: WriteLock = { context: requestContext };
    writeLock.current = lock;
    setWriteState({ context: requestContext, busy: true, outcomeUnknown: false, error: "", notice: "" });

    const isCurrent = () =>
      currentContext.current === requestContext && writeLock.current !== null
      && writeLock.current === lock;
    let retainLock = false;
    const markUnknown = (reason: string) => {
      retainLock = true;
      setWriteState({
        context: requestContext,
        busy: true,
        outcomeUnknown: true,
        error: unknownWriteFailure(reason),
        notice: "",
      });
    };

    try {
      const response = await fetch(url, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body,
      });
      if (!isCurrent()) return;
      if (!response.ok) {
        if (response.status >= 500) {
          markUnknown("HTTP " + response.status);
        } else {
          setWriteState({
            context: requestContext,
            busy: true,
            outcomeUnknown: false,
            error: "Операция отклонена сервером (HTTP " + response.status + "). Введённые данные сохранены.",
            notice: "",
          });
        }
        return;
      }

      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        if (isCurrent()) {
          markUnknown("некорректный ответ");
        }
        return;
      }

      if (!isCurrent()) return;
      if (
        !isValidRow(payload, columns)
        || (expectedId !== undefined && payload.id !== expectedId)
        || (expectedStatus !== undefined && payload[statusKey ?? ""] !== expectedStatus)
      ) {
        markUnknown("ответ не подтверждает ожидаемую запись");
        return;
      }

      if (closeForm) {
        setFormState((previous) => previous.context === requestContext
          ? { context: requestContext, values: blankForm(fields), open: false }
          : previous);
      }

      const refreshed = await loadRows(requestContext, requestEndpoint, columns, true);
      if (!isCurrent()) return;
      setWriteState({
        context: requestContext,
        busy: true,
        outcomeUnknown: false,
        error: "",
        notice: refreshed
          ? "Операция подтверждена; список обновлён."
          : "Операция подтверждена, но список не удалось обновить.",
      });
    } catch {
      if (isCurrent()) {
        markUnknown("нет ответа от сервера");
      }
    } finally {
      if (writeLock.current === lock && !retainLock) writeLock.current = null;
      if (currentContext.current === requestContext) {
        setWriteState((previous) => previous.context === requestContext
          ? { ...previous, busy: false }
          : previous);
      }
    }
  }

  async function onCreate() {
    if (!canWrite || currentContext.current !== context) return;
    const sentValues = matchingForm ? formState.values : blankForm(fields);
    await runWrite({
      requestContext: context,
      requestEndpoint: endpoint,
      url: "/api" + endpoint,
      method: "POST",
      body: JSON.stringify(sentValues),
      closeForm: true,
    });
  }

  async function onStatus(row: Row) {
    if (!statusFlow || !statusFlow.length || !patchPath || !statusKey) return;
    const currentIndex = statusFlow.indexOf(String(row[statusKey] ?? ""));
    if (currentIndex < 0) return;
    const nextStatus = statusFlow[(currentIndex + 1) % statusFlow.length];
    await runWrite({
      requestContext: context,
      requestEndpoint: endpoint,
      url: "/api" + patchPath + "/" + String(row.id),
      method: "PATCH",
      body: JSON.stringify({ status: nextStatus }),
      expectedId: row.id as number,
      expectedStatus: nextStatus,
    });
  }

  async function onAction(row: Row) {
    if (!action) return;
    let pathValid = true;
    const path = action.path.replace(/\{(\w+)\}/g, (_match, key: string) => {
      const value = row[key];
      if (
        typeof value !== "string"
        && !(typeof value === "number" && Number.isFinite(value))
      ) {
        pathValid = false;
        return "";
      }
      return encodeURIComponent(String(value));
    });
    if (!pathValid) return;
    await runWrite({
      requestContext: context,
      requestEndpoint: endpoint,
      url: "/api" + path,
      method: "POST",
      expectedId: row.id as number,
    });
  }

  function toggleForm() {
    setFormState((previous) => {
      const sameContext = previous.context === context;
      const values = sameContext ? previous.values : blankForm(fields);
      return { context, values, open: !(sameContext && previous.open) };
    });
  }

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        <button
          onClick={toggleForm}
          disabled={!canWrite}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          <Plus size={16} /> Добавить
        </button>
      </div>

      {writeError && <p className="mt-3 text-sm text-danger" role="alert">{writeError}</p>}
      {writeNotice && <p className="mt-3 text-sm text-muted" role="status">{writeNotice}</p>}
      {listError && (
        <p className="mt-3 text-sm text-danger" role="alert">
          {listError}{stale ? " Отображаются предыдущие данные; запись заблокирована до успешного обновления." : ""}
        </p>
      )}
      {stale && !listError && (
        <p className="mt-3 text-sm text-muted" role="status">
          Список обновляется; текущие строки могут быть устаревшими.
        </p>
      )}

      {open && (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
          {fields.map((field) => (
            <label key={field.key} className="block">
              <span className="mb-1 block text-xs font-medium text-muted">{field.label}</span>
              <input
                type={field.type ?? "text"}
                value={form[field.key]}
                disabled={busy}
                onChange={(event) =>
                  setFormState({
                    context,
                    values: {
                      ...form,
                      [field.key]: field.type === "number"
                        ? Number(event.target.value)
                        : event.target.value,
                    },
                    open: true,
                  })
                }
                className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </label>
          ))}
          <button
            onClick={() => void onCreate()}
            disabled={!canWrite || busy}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            Сохранить
          </button>
        </div>
      )}

      {clickableStatus && (
        <p className="mt-3 text-xs text-muted">Подсказка: кликните по статусу, чтобы сменить его.</p>
      )}

      <div className="mt-2 overflow-hidden rounded-xl bg-surface shadow-card">
        <div className="flex justify-end border-b border-line px-3 py-2">
          <button
            type="button"
            onClick={() => void loadRows(context, endpoint, columns, true)}
            disabled={loading || busy}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink disabled:opacity-60"
          >
            {listError ? "Повторить" : "Обновить"}
          </button>
        </div>
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              {columns.map((column) => (
                <th key={column.key} className="px-4 py-2.5 font-medium">
                  {column.label}
                </th>
              ))}
              {action && <th className="px-4 py-2.5 font-medium">Действие</th>}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + (action ? 1 : 0)} className="px-4 py-6 text-center text-muted">
                  {loading
                    ? "Загрузка записей…"
                    : listError
                      ? "Список недоступен"
                      : "Записей пока нет"}
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr key={row.id as number} className="border-b border-line last:border-0 hover:bg-sunken">
                {columns.map((column) => {
                  const value = row[column.key];
                  const text = value === null || value === undefined ? "" : String(value);
                  const statusIndex = statusFlow?.indexOf(text) ?? -1;
                  const statusDisabled = !canWrite || statusIndex < 0;
                  return (
                    <td key={column.key} className="px-4 py-2.5 text-ink">
                      {clickableStatus && column.key === statusKey ? (
                        <button
                          disabled={statusDisabled}
                          onClick={() => void onStatus(row)}
                          className="rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-muted hover:bg-accent-soft hover:text-accent-ink disabled:opacity-60"
                        >
                          {text}
                        </button>
                      ) : text}
                    </td>
                  );
                })}
                {action && (
                  <td className="px-4 py-2.5">
                    <button
                      disabled={!canWrite}
                      onClick={() => void onAction(row)}
                      className="rounded-lg border border-accent px-3 py-1 text-xs font-medium text-accent-ink hover:bg-accent-soft disabled:opacity-60"
                    >
                      {action.label}
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
