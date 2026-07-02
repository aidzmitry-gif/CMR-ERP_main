"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";

import { formatNumber } from "@/lib/format";
import {
  fetchTasks,
  patchTask,
  taskKindLabel,
  taskStatusLabel,
  type WmsTask,
} from "@/lib/wms-warehouse";

const KIND_TABS = [
  { id: "", label: "Все" },
  { id: "putaway", label: "Размещение" },
  { id: "pick", label: "Подбор" },
];
const STATUS_STYLES: Record<string, string> = {
  open: "bg-amber-50 text-amber-600",
  in_progress: "bg-blue-50 text-blue-600",
  done: "bg-green-50 text-green-600",
  canceled: "bg-sunken text-muted",
};

export function WmsTasks({ initial }: { initial: WmsTask[] }) {
  const [tasks, setTasks] = useState<WmsTask[]>(initial);
  const [kind, setKind] = useState("");
  const [toLoc, setToLoc] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setTasks(await fetchTasks());
  }
  async function act(t: WmsTask, patch: Record<string, unknown>) {
    setBusy(true);
    await patchTask(t.id, patch);
    await refresh();
    setBusy(false);
  }

  const rows = useMemo(
    () => tasks.filter((t) => (!kind || t.kind === kind)),
    [tasks, kind],
  );

  return (
    <div className="flex-1 overflow-auto p-6">
      <p className="text-sm text-muted">
        Задачи кладовщику. Завершение размещения перемещает товар в постоянную ячейку,
        завершение подбора списывает со склада (движение расхода).
      </p>

      <div className="mt-4 inline-flex rounded-lg border border-line bg-sunken p-1">
        {KIND_TABS.map((k) => (
          <button key={k.id} onClick={() => setKind(k.id)}
            className={clsx("rounded-md px-3 py-1.5 text-sm font-medium",
              kind === k.id ? "bg-surface text-accent-ink shadow-sm" : "text-muted")}>
            {k.label}
          </button>
        ))}
      </div>

      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-surface">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <th className="px-4 py-2 font-medium">Тип</th>
              <th className="px-4 py-2 font-medium">Код</th>
              <th className="px-4 py-2 text-right font-medium">Кол-во</th>
              <th className="px-4 py-2 font-medium">Документ</th>
              <th className="px-4 py-2 font-medium">Статус</th>
              <th className="px-4 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-muted">Задач нет</td></tr>
            )}
            {rows.map((t) => {
              const openish = t.status === "open" || t.status === "in_progress";
              return (
                <tr key={t.id} className="border-b border-line last:border-0">
                  <td className="px-4 py-2.5 text-ink">{taskKindLabel(t.kind)}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-muted">{t.sku_code}</td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink">{formatNumber(t.qty)}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-faint">{t.doc_ref || "—"}</td>
                  <td className="px-4 py-2.5">
                    <span className={clsx("inline-flex rounded-md px-2 py-0.5 text-xs font-medium", STATUS_STYLES[t.status])}>
                      {taskStatusLabel(t.status)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center justify-end gap-1.5">
                      {openish && t.status === "open" && (
                        <button onClick={() => act(t, { status: "in_progress" })} disabled={busy}
                          className="rounded-lg border border-line px-2 py-1 text-xs text-muted hover:bg-sunken disabled:opacity-60">
                          В работу
                        </button>
                      )}
                      {openish && t.kind === "putaway" && (
                        <input value={toLoc[t.id] ?? ""} onChange={(e) => setToLoc((s) => ({ ...s, [t.id]: e.target.value }))}
                          placeholder="ячейка id" inputMode="numeric"
                          className="w-20 rounded-lg border border-line bg-surface px-2 py-1 text-xs outline-none focus:border-accent" />
                      )}
                      {openish && (
                        <button
                          onClick={() => act(t, t.kind === "putaway"
                            ? { status: "done", to_location_id: Number(toLoc[t.id]) || null }
                            : { status: "done" })}
                          disabled={busy}
                          className="rounded-lg bg-accent px-2 py-1 text-xs font-medium text-white hover:bg-accent-ink disabled:opacity-60">
                          Завершить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
