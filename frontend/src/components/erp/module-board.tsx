"use client";

import { Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

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

function blankForm(fields: FieldDef[]): Record<string, string | number> {
  return Object.fromEntries(
    fields.map((f) => [f.key, f.default ?? (f.type === "number" ? 0 : "")]),
  );
}

interface ModuleBoardProps {
  title: string;
  subtitle?: string;
  endpoint: string;
  columns: ColumnDef[];
  fields: FieldDef[];
  statusKey?: string;
  statusFlow?: string[];
  patchPath?: string;
  action?: { label: string; path: string };
}

export function ModuleBoard(props: ModuleBoardProps) {
  return <ModuleBoardScope key={props.endpoint} {...props} />;
}

function ModuleBoardScope({
  title,
  subtitle,
  endpoint,
  columns,
  fields,
  statusKey,
  statusFlow,
  patchPath,
  action,
}: ModuleBoardProps) {
  const [rows, setRows] = useState<Row[]>([]);
  const [form, setForm] = useState<Record<string, string | number>>(() => blankForm(fields));
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [loadState, setLoadState] = useState<"loading" | "ready" | "error" | "auth">("loading");
  const [writeError, setWriteError] = useState<string | null>(null);
  const pendingWrite = useRef(false);
  const mounted = useRef(true);
  const readGeneration = useRef(0);
  const readReady = useRef(false);
  const initialFields = useRef(fields);

  const load = useCallback(() => {
    if (!mounted.current) return;
    const generation = ++readGeneration.current;
    const current = () => mounted.current && generation === readGeneration.current;
    readReady.current = false;
    return Promise.resolve().then(() => fetch(`/api${endpoint}`, { cache: "no-store" })).then(async (res) => {
      if (!current()) return;
      if (res.status === 401 || res.status === 403) {
        setRows([]);
        setOpen(false);
        setForm(blankForm(initialFields.current));
        setLoadState("auth");
        return;
      }
      if (!res.ok) throw new Error("READ_REJECTED");
      const data: unknown = await res.json();
      if (!current()) return;
      if (!Array.isArray(data) || data.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
        throw new Error("INVALID_LIST");
      }
      setRows(data as Row[]);
      readReady.current = true;
      setLoadState("ready");
    }).catch(() => {
      if (current()) setLoadState("error");
    });
  }, [endpoint]);

  async function refresh() {
    if (!mounted.current) return;
    setLoadState("loading");
    await load();
  }

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      readReady.current = false;
      readGeneration.current += 1;
    };
  }, [load]);

  async function write(path: string, options: RequestInit, confirmed?: () => void) {
    if (pendingWrite.current || !mounted.current || !readReady.current) return;
    pendingWrite.current = true;
    setBusy(true);
    setWriteError(null);
    try {
      const response = await fetch(`/api${path}`, options);
      if (!mounted.current) return;
      if (!response.ok) {
        setWriteError(response.status === 401
          ? "Сессия завершена. Войдите в систему заново."
          : response.status === 403
            ? "Недостаточно прав для этого действия."
            : response.status === 409
              ? "Данные изменились. Обновите список и проверьте запись."
              : response.status >= 400 && response.status < 500
                ? "Действие не выполнено. Проверьте поля формы."
                : "Результат действия не подтверждён. Обновите список и проверьте запись перед повтором.");
        return;
      }
      confirmed?.();
      await refresh();
    } catch {
      setWriteError("Результат действия не подтверждён. Обновите список и проверьте запись перед повтором.");
    } finally {
      pendingWrite.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function onCreate() {
    await write(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      }, () => {
        setOpen(false);
        setForm(blankForm(fields));
      });
  }

  async function onStatus(row: Row) {
    if (!statusFlow || !patchPath || !statusKey) return;
    const cur = String(row[statusKey] ?? "");
    const next = statusFlow[(statusFlow.indexOf(cur) + 1) % statusFlow.length];
    await write(`${patchPath}/${row.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: next }),
    });
  }

  async function onAction(row: Row) {
    if (!action) return;
    const path = action.path.replace(/\{(\w+)\}/g, (_, k) => String(row[k] ?? ""));
    await write(path, { method: "POST" });
  }

  const clickableStatus = !!(statusKey && statusFlow && patchPath);
  const canWrite = loadState === "ready" && !busy;

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        <div className="flex gap-2">
          <button onClick={() => void refresh()} disabled={busy}
            className="rounded-lg border border-line px-3 py-2 text-sm text-muted disabled:opacity-60">
            Обновить
          </button>
          <button
            onClick={() => setOpen((v) => !v)} disabled={!canWrite}
            className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
          >
            <Plus size={16} /> Добавить
          </button>
        </div>
      </div>

      {writeError && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{writeError}</p>}
      {loadState === "auth" && <p role="alert" className="mt-3 text-sm text-red-800">Нет доступа к списку. Войдите в систему заново или проверьте права.</p>}
      {loadState === "error" && <p role="alert" className="mt-3 text-sm text-red-800">{rows.length > 0 ? "Список не обновлён. Данные могут быть устаревшими." : "Не удалось загрузить список. Нажмите «Обновить»."}</p>}

      {open && (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
          {fields.map((f) => (
            <label key={f.key} className="block">
              <span className="mb-1 block text-xs font-medium text-muted">{f.label}</span>
              <input
                disabled={!canWrite}
                type={f.type ?? "text"}
                value={form[f.key]}
                onChange={(e) =>
                  setForm({
                    ...form,
                    [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value,
                  })
                }
                className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-accent"
              />
            </label>
          ))}
          <button
            onClick={onCreate}
            disabled={!canWrite}
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
        <table className="w-full text-sm">
          <thead className="border-b border-line text-left text-xs text-muted">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className="px-4 py-2.5 font-medium">
                  {c.label}
                </th>
              ))}
              {action && <th className="px-4 py-2.5 font-medium">Действие</th>}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length + (action ? 1 : 0)} className="px-4 py-6 text-center text-muted">
                  {loadState === "loading" ? "Загрузка…" : loadState === "auth" ? "Доступ к данным не подтверждён" : loadState === "error" ? "Список недоступен" : "Записей пока нет"}
                </td>
              </tr>
            )}
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0 hover:bg-sunken">
                {columns.map((c) => (
                  <td key={c.key} className="px-4 py-2.5 text-ink">
                    {clickableStatus && c.key === statusKey ? (
                      <button
                        disabled={!canWrite}
                        onClick={() => onStatus(row)}
                        className="rounded-md bg-sunken px-2 py-0.5 text-xs font-medium text-muted hover:bg-accent-soft hover:text-accent-ink"
                      >
                        {String(row[c.key] ?? "")}
                      </button>
                    ) : (
                      String(row[c.key] ?? "")
                    )}
                  </td>
                ))}
                {action && (
                  <td className="px-4 py-2.5">
                    <button
                      disabled={!canWrite}
                      onClick={() => onAction(row)}
                      className="rounded-lg border border-accent px-3 py-1 text-xs font-medium text-accent-ink hover:bg-accent-soft"
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
