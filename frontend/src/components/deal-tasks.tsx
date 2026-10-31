"use client";

import clsx from "clsx";
import { CheckSquare, Clock, ListTodo, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  completeDealTask,
  createDealTask,
  type DealTaskView,
  fetchDealTasks,
  localToNaiveUtc,
} from "@/lib/api";

const KIND_LABEL: Record<string, string> = {
  call: "Звонок",
  meeting: "Встреча",
  email: "E-mail",
  chat: "Сообщение",
  doc: "Документ",
  other: "Задача",
};

const STATUS_LABEL: Record<string, string> = {
  open: "Открыта",
  in_progress: "В работе",
  awaiting_control: "Ждёт контроля",
  postponed: "Отложена",
  done: "Выполнена",
  canceled: "Отменена",
  declined: "Отклонена",
};
const ACTIVE_STATUSES = new Set(["open", "in_progress", "awaiting_control", "postponed"]);

function visibleDealIds(task: DealTaskView): number[] {
  const ids = task.crm_links?.length
    ? task.crm_links.map((link) => link.deal_id)
    : [task.deal_id];
  return [...new Set(ids.filter((id): id is number =>
    typeof id === "number" && Number.isSafeInteger(id) && id > 0))];
}

function fmtDue(due: string | null): string {
  if (!due) return "без срока";
  const parsed = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(due) ? due : `${due}Z`);
  return Number.isNaN(parsed.getTime()) ? due : parsed.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function TaskSummary({ task, busy = false, onDone }: {
  task: DealTaskView; busy?: boolean; onDone?: (id: number) => void;
}) {
  const done = task.status === "done";
  const links = visibleDealIds(task);
  const hidden = task.hidden_link_count ?? 0;
  return <li className={clsx("rounded-lg px-3 py-2", task.overdue ? "bg-red-50" : "bg-sunken")}>
    <div className="flex items-start gap-2">
      <div className="min-w-0 flex-1">
        <div className={clsx("break-words text-sm", done ? "text-faint line-through" : "text-muted")}>{task.title}</div>
        <div className={clsx("mt-1 inline-flex flex-wrap items-center gap-1 text-xs", task.overdue ? "font-semibold text-red-600" : "text-faint")}>
          <Clock size={11} /> {KIND_LABEL[task.kind] ?? task.kind} · {fmtDue(task.due_at)}
          {task.overdue ? " · просрочено" : ""} · {STATUS_LABEL[task.status] ?? "Статус не указан"}
        </div>
        {task.description && <p className="mt-2 whitespace-pre-wrap break-words text-sm text-ink">{task.description}</p>}
        {(links.length > 0 || hidden > 0) && <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted">
          {links.map((id) => <Link key={id} href={`/crm/deals/${id}`} className="underline">Сделка {id}</Link>)}
          {hidden > 0 && <span>Скрытых связей: {hidden}</span>}
        </div>}
        {links.length === 0 && hidden === 0 && <span className="mt-1 block text-xs text-muted">Без привязки к сделке</span>}
      </div>
      {task.imported && <span className="shrink-0 text-xs text-muted">Импорт · только чтение</span>}
      {!task.imported && done && <span className="shrink-0 text-xs font-medium text-green-600">✓ готово</span>}
      {!task.imported && ACTIVE_STATUSES.has(task.status) && onDone && <button
        type="button" onClick={() => onDone(task.id)} disabled={busy} title="Выполнено"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-faint hover:bg-green-50 hover:text-green-600 disabled:opacity-60"
      ><CheckSquare size={16} /></button>}
    </div>
  </li>;
}

/** Блок «Задачи» на экране сделки (SALES-41): список с подсветкой просрочки,
 * постановка задачи (срок опционально), отметка «Выполнено». */
export function DealTasks({ dealId }: { dealId: string }) {
  return <ScopedDealTasks key={dealId} dealId={dealId} />;
}

function ScopedDealTasks({ dealId }: { dealId: string }) {
  const [tasks, setTasks] = useState<DealTaskView[]>([]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [revision, setRevision] = useState(0);
  const active = useRef(false);
  const readVersion = useRef(0);
  const mutationInFlight = useRef(false);

  const refresh = useCallback(() => {
    const version = ++readVersion.current;
    const current = () => active.current && version === readVersion.current;
    return fetchDealTasks(dealId).then((rows) => {
      if (current()) setTasks(rows);
    }).catch(() => {
      // A successful create/complete must not be reported as a failed mutation
      // solely because the follow-up list request failed.
      if (current()) setLoadError(true);
    }).finally(() => {
      if (current()) setLoading(false);
    });
  }, [dealId]);

  useEffect(() => {
    active.current = true;
    void refresh();
    return () => { active.current = false; readVersion.current += 1; };
  }, [refresh, revision]);

  async function onAdd() {
    if (!title.trim() || mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const saved = await createDealTask(dealId, { title: title.trim(), due_at: due ? localToNaiveUtc(due) : null });
      if (!active.current) return;
      if (!saved) {
        setError("Не удалось создать задачу. Повторите попытку.");
        return;
      }
      setTitle("");
      setDue("");
      setLoading(true);
      setLoadError(false);
      await refresh();
    } catch {
      if (active.current) setError("Не удалось создать задачу. Повторите попытку.");
    } finally {
      mutationInFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  async function onDone(id: number) {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const saved = await completeDealTask(id);
      if (!active.current) return;
      if (!saved) {
        setError("Не удалось завершить задачу. Повторите попытку.");
        return;
      }
      setLoading(true);
      setLoadError(false);
      await refresh();
    } catch {
      if (active.current) setError("Не удалось завершить задачу. Повторите попытку.");
    } finally {
      mutationInFlight.current = false;
      if (active.current) setBusy(false);
    }
  }

  const openCount = tasks.filter((t) => ACTIVE_STATUSES.has(t.status)).length;

  return (
    <div className="mt-4 rounded-xl border border-line p-4">
      <div className="flex items-center gap-2 font-semibold text-ink">
        <ListTodo size={18} className="text-accent-ink" />
        Задачи <span className="font-medium text-accent-ink">({loading || loadError ? "—" : openCount} откр.)</span>
        <Link href="/crm/tasks" className="ml-auto text-xs font-normal text-accent-ink underline">Все задачи</Link>
      </div>

      {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}

      {loading && <p role="status" className="mt-3 text-sm text-muted">Загрузка задач…</p>}
      {loadError && <p role="alert" className="mt-3 text-sm text-red-600">Не удалось загрузить задачи. <button type="button" className="underline" onClick={() => {
        setLoading(true); setLoadError(false); setRevision((value) => value + 1);
      }}>Повторить загрузку</button></p>}
      {!loading && !loadError && <ul className="mt-3 space-y-2">
        {tasks.length === 0 && <li className="text-sm text-muted">Задач пока нет</li>}
        {tasks.map((task) => <TaskSummary key={task.id} task={task} busy={busy} onDone={onDone} />)}
      </ul>}

      <div className="mt-3 flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Что сделать…"
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <input
          type="datetime-local"
          value={due}
          onChange={(e) => setDue(e.target.value)}
          title="Срок (необязательно)"
          className="shrink-0 rounded-lg border border-line bg-surface px-2 py-2 text-sm text-ink outline-none focus:border-accent"
        />
        <button
          onClick={onAdd}
          disabled={busy || !title.trim()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-ink disabled:opacity-60"
        >
          <Plus size={16} /> Задача
        </button>
      </div>
    </div>
  );
}
