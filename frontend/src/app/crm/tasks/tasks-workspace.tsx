"use client";

import { useEffect, useState } from "react";
import { TaskSummary } from "@/components/deal-tasks";
import { fetchAllCrmTasks, type DealTaskView } from "@/lib/api";

const PAGE_SIZE = 50;

export function TasksWorkspace() {
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<
    { status: "loading" } | { status: "error" } | { status: "ok"; rows: DealTaskView[] }
  >({ status: "loading" });

  useEffect(() => {
    let live = true;
    void fetchAllCrmTasks(offset, PAGE_SIZE).then((rows) => {
      if (live) setState({ status: "ok", rows });
    }).catch(() => {
      if (live) setState({ status: "error" });
    });
    return () => { live = false; };
  }, [offset, revision]);

  function go(next: number) {
    setState({ status: "loading" });
    setOffset(next);
  }

  return <section className="mt-4 rounded-xl border border-line bg-surface p-4" aria-label="Список задач CRM">
    {state.status === "loading" && <p role="status" className="text-sm text-muted">Загрузка задач…</p>}
    {state.status === "error" && <p role="alert" className="text-sm text-red-600">
      Не удалось загрузить задачи. <button type="button" className="underline" onClick={() => {
        setState({ status: "loading" });
        setRevision((value) => value + 1);
      }}>Повторить</button>
    </p>}
    {state.status === "ok" && <>
      {state.rows.length === 0 && <p className="text-sm text-muted">
        {offset === 0 ? "Задач пока нет." : "На этой странице задач нет."}
      </p>}
      {state.rows.length > 0 && <ul className="space-y-2">
        {state.rows.map((task) => <TaskSummary key={task.id} task={task} />)}
      </ul>}
      <div className="mt-4 flex items-center gap-3 text-sm">
        <button type="button" className="underline disabled:opacity-40" disabled={offset === 0}
          onClick={() => go(Math.max(0, offset - PAGE_SIZE))}>Назад</button>
        <span>Страница {Math.floor(offset / PAGE_SIZE) + 1}</span>
        <button type="button" className="underline disabled:opacity-40" disabled={state.rows.length < PAGE_SIZE}
          onClick={() => go(offset + PAGE_SIZE)}>Далее</button>
      </div>
    </>}
  </section>;
}
