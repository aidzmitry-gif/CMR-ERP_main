"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import {
  type ActivityResult, readActivityMessages, readActivityTasks, validActivityId,
} from "@/lib/lead-activity";

type Props = { dealId?: number; nextStepAt: string | null; nextStepNote: string };

function dateLabel(value: string | null) {
  if (!value) return "Срок не указан";
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? "Некорректная дата"
    : `${date.toLocaleString("ru-RU", { timeZone: "Europe/Minsk" })} (Минск)`;
}

function useFeed<T>(dealId: number, read: (id: number, signal?: AbortSignal) => Promise<ActivityResult<T>>) {
  const [result, setResult] = useState<ActivityResult<T> | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    void read(dealId, controller.signal).then((value) => { if (active) setResult(value); });
    return () => { active = false; controller.abort(); };
  }, [dealId, read, attempt]);
  return { result, retry: () => { setResult(null); setAttempt((value) => value + 1); } };
}

function FeedState({ result, retry, empty }: {
  result: ActivityResult<unknown> | null; retry: () => void; empty: string;
}) {
  if (!result) return <p role="status" className="text-sm text-muted">Загрузка…</p>;
  if (result.status === "error") return <div role="alert" className="text-sm text-muted">
    {result.reason === "access" ? "Недостаточно прав для просмотра данных сделки."
      : result.reason === "missing" ? "Связанная сделка недоступна."
        : "Не удалось загрузить данные."}{" "}
    <button type="button" onClick={retry} className="font-semibold text-accent-ink">Повторить</button>
  </div>;
  return result.rows.length === 0 ? <p className="text-sm text-muted">{empty}</p> : null;
}

function LinkedActivity({ dealId }: { dealId: number }) {
  const tasks = useFeed(dealId, readActivityTasks);
  const messages = useFeed(dealId, readActivityMessages);
  return <>
    <Card>
      <CardHeader>Задачи связанной сделки</CardHeader>
      <CardBody className="space-y-3">
        <FeedState {...tasks} empty="В связанной сделке задач пока нет." />
        {tasks.result?.status === "ok" && <ul className="space-y-2">
          {tasks.result.rows.map((task) => <li key={task.id} className="rounded-lg bg-sunken p-3 text-sm">
            <div className="font-semibold text-ink">{task.title}</div>
            <div className="text-muted">{task.status === "done" ? "Выполнена"
              : task.status === "canceled" ? "Отменена" : "Открыта"} · {dateLabel(task.due_at)}
              {task.overdue && task.status === "open" ? " · просрочена" : ""}</div>
          </li>)}
        </ul>}
        <Link href={`/crm/deals/${dealId}`} className="text-sm font-semibold text-accent-ink">
          Открыть сделку CRM-{dealId} для работы с задачами
        </Link>
      </CardBody>
    </Card>
    <Card>
      <CardHeader>История общения связанной сделки</CardHeader>
      <CardBody className="space-y-3">
        <p className="text-xs text-muted">Сохранённые записи истории. Наличие записи не подтверждает доставку сообщения клиенту.</p>
        <FeedState {...messages} empty="В связанной сделке записей общения пока нет." />
        {messages.result?.status === "ok" && <ul className="space-y-2">
          {messages.result.rows.map((message) => <li key={message.id} className="rounded-lg bg-sunken p-3 text-sm">
            <div className="text-xs text-muted">{message.channel} · {message.author} · {dateLabel(message.created_at)}</div>
            <p className="mt-1 whitespace-pre-wrap break-words text-ink">{message.text}</p>
          </li>)}
        </ul>}
      </CardBody>
    </Card>
  </>;
}

export function LeadActivity({ dealId, nextStepAt, nextStepNote }: Props) {
  return <>
    <Card>
      <CardHeader>Следующий шаг по лиду</CardHeader>
      <CardBody className="space-y-2 text-sm text-muted">
        {nextStepAt || nextStepNote ? <>
          <p className="whitespace-pre-wrap break-words text-ink">{nextStepNote || "Заметка не указана"}</p>
          <p>{dateLabel(nextStepAt)}</p>
        </> : <p>Следующий шаг по лиду не задан.</p>}
      </CardBody>
    </Card>
    {validActivityId(dealId) ? <LinkedActivity key={dealId} dealId={dealId} /> : <Card>
      <CardHeader>Задачи и история общения</CardHeader>
      <CardBody className="text-sm text-muted">
        Связанная сделка не указана. Её задачи и история общения пока недоступны.
      </CardBody>
    </Card>}
  </>;
}
