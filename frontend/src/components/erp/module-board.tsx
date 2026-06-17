"use client";

import { Plus } from "lucide-react";
import { useEffect, useState } from "react";

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
  const [rows, setRows] = useState<Row[]>([]);
  const [form, setForm] = useState<Record<string, string | number>>(() => blankForm(fields));
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  async function refresh() {
    try {
      const res = await fetch(`/api${endpoint}`, { cache: "no-store" });
      if (res.ok) setRows((await res.json()) as Row[]);
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint]);

  async function onCreate() {
    setBusy(true);
    try {
      await fetch(`/api${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
    } catch {
      /* ignore */
    }
    setBusy(false);
    setOpen(false);
    setForm(blankForm(fields));
    await refresh();
  }

  async function onStatus(row: Row) {
    if (!statusFlow || !patchPath || !statusKey) return;
    const cur = String(row[statusKey] ?? "");
    const next = statusFlow[(statusFlow.indexOf(cur) + 1) % statusFlow.length];
    await fetch(`/api${patchPath}/${row.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: next }),
    });
    await refresh();
  }

  async function onAction(row: Row) {
    if (!action) return;
    const path = action.path.replace(/\{(\w+)\}/g, (_, k) => String(row[k] ?? ""));
    await fetch(`/api${path}`, { method: "POST" });
    await refresh();
  }

  const clickableStatus = !!(statusKey && statusFlow && patchPath);

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-ink"
        >
          <Plus size={16} /> Добавить
        </button>
      </div>

      {open && (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-surface p-4 shadow-card">
          {fields.map((f) => (
            <label key={f.key} className="block">
              <span className="mb-1 block text-xs font-medium text-muted">{f.label}</span>
              <input
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
            disabled={busy}
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
                  Записей пока нет
                </td>
              </tr>
            )}
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0 hover:bg-sunken">
                {columns.map((c) => (
                  <td key={c.key} className="px-4 py-2.5 text-ink">
                    {clickableStatus && c.key === statusKey ? (
                      <button
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
                      onClick={() => onAction(row)}
                      className="rounded-lg border border-accent px-3 py-1 text-xs font-medium text-accent-ink hover:bg-blue-50"
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
