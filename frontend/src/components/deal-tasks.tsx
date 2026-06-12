"use client";

import clsx from "clsx";
import { CheckSquare, Clock, ListTodo, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import {
  completeDealTask,
  createDealTask,
  type DealTaskView,
  fetchDealTasks,
} from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  call: "Звонок",
  meeting: "Встреча",
  email: "E-mail",
  chat: "Сообщение",
  doc: "Документ",
  other: "Задача",
};

function fmtDue(due: string | null): string {
  if (!due) return "без срока";
  return new Date(due).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Блок «Задачи» на экране сделки (SALES-41): список с подсветкой просрочки,
 * постановка задачи (срок опционально), отметка «Выполнено». */
export function DealTasks({ dealId }: { dealId: string }) {
  const [tasks, setTasks] = useState<DealTaskView[]>([]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setTasks(await fetchDealTasks(dealId));
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  async function onAdd() {
    if (!title.trim()) return;
    setBusy(true);
    await createDealTask(dealId, { title: title.trim(), due_at: due || null });
    setTitle("");
    setDue("");
    await refresh();
    setBusy(false);
  }

  async function onDone(id: number) {
    setBusy(true);
    await completeDealTask(id);
    await refresh();
    setBusy(false);
  }

  const openCount = tasks.filter((t) => t.status === "open").length;

  return (
    <div className="mt-4 rounded-xl border border-slate-200 p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <ListTodo size={18} className="text-brand-600" />
        Задачи <span className="font-medium text-brand-600">({openCount} откр.)</span>
      </div>

      <ul className="mt-3 space-y-2">
        {tasks.length === 0 && <li className="text-sm text-muted">Задач пока нет</li>}
        {tasks.map((t) => {
          const done = t.status === "done";
          return (
            <li
              key={t.id}
              className={clsx(
                "flex items-center gap-2 rounded-lg px-3 py-2",
                t.overdue ? "bg-red-50" : "bg-slate-50",
              )}
            >
              <div className="min-w-0 flex-1">
                <div
                  className={clsx(
                    "truncate text-sm",
                    done ? "text-slate-400 line-through" : "text-slate-700",
                  )}
                >
                  {t.title}
                </div>
                <span
                  className={clsx(
                    "inline-flex items-center gap-1 text-xs",
                    t.overdue ? "font-semibold text-red-600" : "text-slate-400",
                  )}
                >
                  <Clock size={11} />
                  {KIND_LABEL[t.kind] ?? t.kind} · {fmtDue(t.due_at)}
                  {t.overdue ? " · просрочено" : ""}
                </span>
              </div>
              {done ? (
                <span className="shrink-0 text-xs font-medium text-green-600">✓ готово</span>
              ) : (
                <button
                  onClick={() => onDone(t.id)}
                  disabled={busy}
                  title="Выполнено"
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
                >
                  <CheckSquare size={16} />
                </button>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Что сделать…"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
        />
        <input
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          title="Срок (необязательно)"
          className="shrink-0 rounded-lg border border-slate-200 px-2 py-2 text-sm outline-none focus:border-brand"
        />
        <button
          onClick={onAdd}
          disabled={busy || !title.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
        >
          <Plus size={16} /> Задача
        </button>
      </div>
    </div>
  );
}
