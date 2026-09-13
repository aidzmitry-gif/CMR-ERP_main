"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { EMAIL_STATUS, type DocumentEmail } from "@/lib/document-email-api";
import { fetchInvoiceNotifications, prepareInvoiceNotificationEmail, sendInvoiceNotificationEmail, type InvoiceNotification } from "@/lib/invoice-notification-api";

const eventLabel: Record<InvoiceNotification["event_type"], string> = {
  "sales.invoice.expiring": "Срок действия счёта",
  "sales.invoice.cancelled": "Аннулирование счёта",
};

const stateLabel: Record<InvoiceNotification["state"], string> = {
  pending: "Можно подготовить письмо",
  blocked: "Требуется сверка",
};

const message = (error: unknown) => error instanceof Error ? error.message : "Не удалось выполнить операцию с уведомлением.";

type RegisterProps = { organizationId: number; dealId: string; documentId: number };

export function InvoiceNotificationRegister(props: RegisterProps) {
  return <ScopedNotificationRegister key={`${props.organizationId}/${props.dealId}/${props.documentId}`} {...props} />;
}

function ScopedNotificationRegister({ organizationId, dealId, documentId }: RegisterProps) {
  const [rows, setRows] = useState<InvoiceNotification[] | null>(null);
  const [emails, setEmails] = useState<Record<number, DocumentEmail>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    void fetchInvoiceNotifications(organizationId, dealId, documentId)
      .then((value) => { if (active) setRows(value); })
      .catch((value: unknown) => { if (active) setError(message(value)); });
    return () => { active = false; };
  }, [organizationId, dealId, documentId, revision]);

  async function prepare(row: InvoiceNotification) {
    if (busy !== null) return;
    setBusy(row.id); setError("");
    try {
      const email = await prepareInvoiceNotificationEmail(organizationId, dealId, row.id);
      setEmails((current) => ({ ...current, [row.id]: email }));
    } catch (value) { setError(message(value)); }
    finally { setBusy(null); }
  }

  async function send(row: InvoiceNotification) {
    const email = emails[row.id];
    if (!email || busy !== null) return;
    setBusy(row.id); setError("");
    try {
      const result = await sendInvoiceNotificationEmail(dealId, email.id);
      setEmails((current) => ({ ...current, [row.id]: result }));
    } catch (value) { setError(message(value)); }
    finally { setBusy(null); }
  }

  return <section aria-label="Уведомления клиенту по счёту" className="space-y-3 rounded-lg border border-line p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="font-semibold">Уведомления клиенту</h3>
      <Button variant="ghost" disabled={busy !== null} onClick={() => setRevision((value) => value + 1)}>Обновить</Button>
    </div>
    <p className="text-xs text-muted">Решение и адрес взяты из сохранённой версии счёта. Подготовка не отправляет письмо; отправка требует отдельного подтверждения.</p>
    {rows === null && !error && <p role="status">Загрузка решений…</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {rows?.length === 0 && !error && <p>Для этой версии счёта уведомлений нет.</p>}
    {rows?.map((row) => {
      const email = emails[row.id];
      return <article key={row.id} className="space-y-2 rounded border border-line bg-surface p-3 text-sm">
        <h4 className="font-semibold">{eventLabel[row.event_type]} · решение ID {row.id}</h4>
        <p>{stateLabel[row.state]} · {row.recipient || "адрес отсутствует"}</p>
        {row.reason && <p className="text-red-700">Причина: {row.reason}</p>}
        {email ? <>
          <p>Письмо: {EMAIL_STATUS[email.status] || email.status} · ID {email.id}</p>
          <dl className="space-y-1">
            <div><dt className="font-medium">Отправитель</dt><dd>{email.sender}</dd></div>
            <div><dt className="font-medium">Получатели</dt><dd>{email.to.join(", ")}</dd></div>
            {email.cc.length > 0 && <div><dt className="font-medium">Копия</dt><dd>{email.cc.join(", ")}</dd></div>}
            <div><dt className="font-medium">Тема</dt><dd>{email.subject}</dd></div>
          </dl>
          <pre aria-label="Текст подготовленного уведомления" className="whitespace-pre-wrap break-words font-sans">{email.body}</pre>
          {email.status === "prepared" && <Button disabled={busy !== null} onClick={() => void send(row)}>Подтвердить отправку письма</Button>}
          {email.status !== "prepared" && <p className="text-muted">Состояние почтовой очереди подтверждено сервером. Повторная постановка не требуется.</p>}
        </> : row.state === "pending" && <Button variant="secondary" disabled={busy !== null} onClick={() => void prepare(row)}>{busy === row.id ? "Подготавливаем…" : "Подготовить письмо"}</Button>}
      </article>;
    })}
  </section>;
}
