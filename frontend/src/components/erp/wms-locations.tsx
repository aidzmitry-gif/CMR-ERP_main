"use client";

import clsx from "clsx";
import { Plus } from "lucide-react";
import { useState } from "react";

import { createLocation, fetchLocations, locationLabel, type WmsLocation } from "@/lib/wms-ops";

export function WmsLocations({ initial }: { initial: WmsLocation[] }) {
  const [rows, setRows] = useState<WmsLocation[]>(initial);
  const [form, setForm] = useState({ warehouse: "Главный", zone: "", code: "", title: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function refresh() {
    setRows(await fetchLocations());
  }

  async function onAdd() {
    if (!form.code.trim()) {
      setError(true);
      setTimeout(() => setError(false), 900);
      return;
    }
    setBusy(true);
    const ok = await createLocation({
      warehouse: form.warehouse.trim() || "Главный",
      zone: form.zone.trim(),
      code: form.code.trim(),
      title: form.title.trim(),
    });
    if (ok) {
      setForm({ warehouse: form.warehouse, zone: form.zone, code: "", title: "" });
      await refresh();
    }
    setBusy(false);
  }

  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Адресное хранение: зоны и ячейки склада. Привязываются к движениям (приёмка/перемещение).
      </p>

      <div className="mt-4 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Склад</th>
              <th className="px-4 py-2 font-medium">Зона</th>
              <th className="px-4 py-2 font-medium">Ячейка</th>
              <th className="px-4 py-2 font-medium">Описание</th>
              <th className="px-4 py-2 font-medium">Статус</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-6 text-center text-muted">
                  Ячеек пока нет — добавьте первую
                </td>
              </tr>
            )}
            {rows.map((l) => (
              <tr key={l.id} className="border-b border-line last:border-0">
                <td className="px-4 py-2.5 text-muted">{l.warehouse}</td>
                <td className="px-4 py-2.5 text-muted">{l.zone || "—"}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-ink">{locationLabel(l)}</td>
                <td className="px-4 py-2.5 text-muted">{l.title || "—"}</td>
                <td className="px-4 py-2.5">
                  <span
                    className={clsx(
                      "inline-flex rounded-md px-2 py-0.5 text-xs font-medium",
                      l.is_active ? "bg-green-50 text-green-600" : "bg-sunken text-muted",
                    )}
                  >
                    {l.is_active ? "Активна" : "Архив"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-line">
              <td className="px-3 py-2">
                <input
                  value={form.warehouse}
                  onChange={(e) => setForm({ ...form, warehouse: e.target.value })}
                  placeholder="Склад"
                  className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                />
              </td>
              <td className="px-3 py-2">
                <input
                  value={form.zone}
                  onChange={(e) => setForm({ ...form, zone: e.target.value })}
                  placeholder="Зона"
                  className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                />
              </td>
              <td className="px-3 py-2">
                <input
                  value={form.code}
                  onChange={(e) => setForm({ ...form, code: e.target.value })}
                  placeholder="Ячейка*"
                  className={clsx(
                    "w-full rounded-lg border bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent",
                    error ? "border-amber-500" : "border-line",
                  )}
                />
              </td>
              <td className="px-3 py-2">
                <input
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                  placeholder="Описание"
                  className="w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-accent"
                />
              </td>
              <td className="px-3 py-2">
                <button
                  onClick={onAdd}
                  disabled={busy}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
                >
                  <Plus size={15} /> Добавить
                </button>
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}
