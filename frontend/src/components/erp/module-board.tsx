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
}: {
  title: string;
  subtitle?: string;
  endpoint: string;
  columns: ColumnDef[];
  fields: FieldDef[];
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

  return (
    <main className="flex-1 overflow-auto p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-ink">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          <Plus size={16} /> Добавить
        </button>
      </div>

      {open && (
        <div className="mt-4 flex flex-wrap items-end gap-3 rounded-xl bg-white p-4 shadow-card">
          {fields.map((f) => (
            <label key={f.key} className="block">
              <span className="mb-1 block text-xs font-medium text-slate-500">{f.label}</span>
              <input
                type={f.type ?? "text"}
                value={form[f.key]}
                onChange={(e) =>
                  setForm({
                    ...form,
                    [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value,
                  })
                }
                className="rounded-lg border border-slate-200 px-3 py-2 text-sm outline-none focus:border-brand"
              />
            </label>
          ))}
          <button
            onClick={onCreate}
            disabled={busy}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            Сохранить
          </button>
        </div>
      )}

      <div className="mt-4 overflow-hidden rounded-xl bg-white shadow-card">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-100 text-left text-xs text-muted">
            <tr>
              {columns.map((c) => (
                <th key={c.key} className="px-4 py-2.5 font-medium">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-6 text-center text-muted">
                  Записей пока нет
                </td>
              </tr>
            )}
            {rows.map((row, i) => (
              <tr key={i} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                {columns.map((c) => (
                  <td key={c.key} className="px-4 py-2.5 text-ink">
                    {String(row[c.key] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
