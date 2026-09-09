"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { EMAIL_REASON, EMAIL_STATUS, emailRequest, emailUrl, type DocumentEmail, type EmailAttempt, type EmailOptions } from "@/lib/document-email-api";

const date = (value: string | null) => value ? new Date(value).toLocaleString("ru-RU") : "—";
const split = (value: string) => value.split(/[;,]/).map(v => v.trim()).filter(Boolean);

export function DocumentEmailPanel({ dealId }: { dealId: string }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<EmailOptions | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("Документы по вашей сделке");
  const [body, setBody] = useState("Направляем документы по вашей сделке.");
  const [preview, setPreview] = useState<DocumentEmail | null>(null);
  const [history, setHistory] = useState<DocumentEmail[]>([]);
  const [attempts, setAttempts] = useState<Record<string, EmailAttempt[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [duplicateAck, setDuplicateAck] = useState<string | null>(null);
  const key = useRef("");
  const locked = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const pending = history.some(e => ["queued", "sending", "retry_wait"].includes(e.status));
  useEffect(() => {
    if (!open || !pending) return;
    let ignore = false;
    const timer = setInterval(() => {
      void emailRequest<DocumentEmail[]>(emailUrl(dealId)).then(rows => {
        if (!ignore) setHistory(rows);
      }).catch(() => { if (!ignore) setError("Не удалось обновить статус. Показанные данные могут быть устаревшими."); });
    }, 3000);
    return () => { ignore = true; clearInterval(timer); };
  }, [dealId, open, pending]);
  async function action(work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError(null);
    try { await work(); }
    catch (reason) { if (mounted.current) setError(reason instanceof Error ? reason.message : "Ошибка запроса CRM"); }
    finally { locked.current = false; if (mounted.current) setBusy(false); }
  }
  async function refresh() {
    const rows = await emailRequest<DocumentEmail[]>(emailUrl(dealId));
    if (mounted.current) setHistory(rows);
  }
  async function show() {
    setOpen(true);
    await action(async () => {
      const [opts, rows] = await Promise.all([emailRequest<EmailOptions>(emailUrl(dealId, "/options")), emailRequest<DocumentEmail[]>(emailUrl(dealId))]);
      if (!mounted.current) return;
      setOptions(opts); setHistory(rows);
      setSelected(["invoice", "contract"].flatMap(kind => {
        const doc = opts.documents.find(d => d.kind === kind && d.available && !d.superseded_by_id);
        return doc ? [doc.id] : [];
      }));
    });
  }
  async function prepare() {
    await action(async () => {
      key.current ||= crypto.randomUUID();
      const email = await emailRequest<DocumentEmail>(emailUrl(dealId, "/prepare"), {
        request_key: key.current, document_ids: selected, to: split(to), cc: split(cc), subject, body,
      });
      if (mounted.current) setPreview(email.status === "prepared" ? email : null);
      await refresh();
    });
  }
  async function send(email: DocumentEmail) {
    await action(async () => {
      try { await emailRequest<DocumentEmail>(emailUrl(dealId, `/${email.id}/send`), {}); }
      catch (reason) {
        await refresh().catch(() => undefined);
        throw new Error(`${reason instanceof Error ? reason.message : "Ответ CRM не получен"}. Проверьте историю перед новой отправкой.`);
      }
      key.current = "";
      if (mounted.current) setPreview(null);
      await refresh();
    });
  }
  const inputClass = "mt-1 w-full rounded border border-line bg-surface p-2";
  return <div className="mt-3 border-t border-line pt-3">
    <Button variant="secondary" size="sm" block onClick={() => open ? setOpen(false) : void show()}>Email документов</Button>
    {open && <section aria-label="Отправка документов по email" className="mt-3 space-y-3 text-sm">
      <p className="font-semibold text-ink">Отправка документов по email</p>
      <p className="text-xs text-muted">Выберите выпущенные версии, проверьте адресатов и PDF, затем подтвердите отправку.</p>
      {error && <p role="alert" className="rounded border border-line p-2 text-danger">{error}</p>}
      {options?.configuration_error && <p role="status">{options.configuration_error}</p>}
      {options && !options.enabled && <p role="status">Исходящая отправка ещё не включена администратором.</p>}
      {!preview && options && <>
        <p>От: <strong>{options.sender ?? "не настроен"}</strong></p>
        <fieldset className="space-y-2"><legend className="font-medium">Документы</legend>
          {options.documents.length === 0 && <p className="text-muted">Счета и договоры ещё не выпущены.</p>}
          {options.documents.map(doc => <label key={doc.id} className="flex items-start gap-2">
            <input type="checkbox" checked={selected.includes(doc.id)} disabled={!doc.available || busy}
              onChange={event => { key.current = ""; setSelected(event.target.checked ? [...selected, doc.id] : selected.filter(id => id !== doc.id)); }} />
            <span>{doc.kind === "invoice" ? "Счёт" : "Договор"} {doc.number} · версия {doc.version ?? "не сохранена"}
              {!doc.available && <span className="block text-xs text-muted">Нет доступного выпущенного оригинала</span>}
              {doc.superseded_by_id && <span className="block text-xs text-muted">Историческая версия: выпущена замена</span>}
            </span>
          </label>)}
        </fieldset>
        <label className="block">Кому (To)<input type="email" multiple value={to} disabled={busy} onChange={event => { key.current = ""; setTo(event.target.value); }} className={inputClass} placeholder="client@example.com" /></label>
        <label className="block">Копия (CC)<input type="email" multiple value={cc} disabled={busy} onChange={event => { key.current = ""; setCc(event.target.value); }} className={inputClass} /></label>
        <label className="block">Тема<input value={subject} maxLength={250} disabled={busy} onChange={event => { key.current = ""; setSubject(event.target.value); }} className={inputClass} /></label>
        <label className="block">Текст письма<textarea value={body} maxLength={10000} disabled={busy} onChange={event => { key.current = ""; setBody(event.target.value); }} className={inputClass} /></label>
        <Button size="sm" disabled={busy || !selected.length || !to.trim() || !options.sender} onClick={() => void prepare()}>Подготовить и проверить</Button>
      </>}
      {preview && <div className="space-y-2 rounded border border-line p-3">
        <p className="font-semibold">Подготовлено — не отправлено</p>
        <p>От: {preview.sender}</p><p>Кому: {preview.to.join(", ")}</p><p>Копия: {preview.cc.join(", ") || "нет"}</p>
        <p>Тема: {preview.subject}</p><p className="whitespace-pre-wrap">{preview.body}</p>
        {preview.attachments.map((file, index) => <a key={file.document_id} className="block text-accent-ink underline" target="_blank" rel="noreferrer"
          href={emailUrl(dealId, `/${preview.id}/attachments/${index}`)}>{file.number} · версия {file.version} · PDF · {Math.ceil(file.size / 1024)} КБ</a>)}
        <p className="text-xs text-muted">Будут отправлены именно эти PDF. После подтверждения состав письма фиксирован.</p>
        <div className="flex flex-wrap gap-2"><Button size="sm" disabled={busy || !options?.enabled} onClick={() => void send(preview)}>Подтвердить отправку</Button>
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => { key.current = ""; setPreview(null); }}>Изменить письмо</Button></div>
      </div>}
      <div className="flex items-center justify-between"><h4 className="font-semibold">История отправки</h4>
        <button type="button" disabled={busy} onClick={() => void action(refresh)} className="text-accent-ink">Обновить</button></div>
      {history.map(email => <article key={email.id} className="space-y-1 rounded border border-line p-3">
        <p className="font-medium">{EMAIL_STATUS[email.status] ?? "Статус не распознан"}</p>
        <p>{email.subject}</p><p>To: {email.to.join(", ")}{email.cc.length > 0 && ` · CC: ${email.cc.join(", ")}`}</p>
        <p className="text-xs text-muted">Подготовлено: {date(email.created_at)} · Попыток: {email.attempt_count}</p>
        {email.accepted_at && <p className="text-xs">Принято сервером: {date(email.accepted_at)}. Доставка и прочтение не подтверждены.</p>}
        {email.next_attempt_at && email.status === "retry_wait" && <p className="text-xs">Повтор после: {date(email.next_attempt_at)}</p>}
        {email.last_reason && email.status !== "accepted" && <p>{EMAIL_REASON[email.last_reason] ?? "Проверьте результат попытки в CRM."}</p>}
        {email.attachments.map((file, index) => <a key={file.document_id} className="block text-xs text-accent-ink underline" target="_blank" rel="noreferrer"
          href={emailUrl(dealId, `/${email.id}/attachments/${index}`)}>{file.number} · версия {file.version} · PDF</a>)}
        <details className="text-xs text-muted" onToggle={event => {
          if (event.currentTarget.open) void action(async () => {
            const detail = await emailRequest<DocumentEmail & { attempts: EmailAttempt[] }>(emailUrl(dealId, `/${email.id}`));
            if (mounted.current) setAttempts(current => ({ ...current, [email.id]: detail.attempts }));
          });
        }}><summary>Попытки и идентификатор</summary><p className="break-all">{email.message_id}</p>
          {attempts[email.id]?.map(attempt => <p key={attempt.number} className="mt-1">
            № {attempt.number} · {date(attempt.started_at)} · {EMAIL_STATUS[attempt.status] ?? "Статус не распознан"}
            {attempt.smtp_code && ` · SMTP ${attempt.smtp_code}`}
            {attempt.reason && attempt.status !== "accepted" && ` · ${EMAIL_REASON[attempt.reason] ?? "Ошибка попытки"}`}
          </p>)}
        </details>
        {email.status === "prepared" && <button type="button" disabled={busy} onClick={() => setPreview(email)} className="text-accent-ink">Проверить перед отправкой</button>}
        {email.status === "uncertain" && <label className="flex gap-2"><input type="checkbox" checked={duplicateAck === email.id} onChange={event => setDuplicateAck(event.target.checked ? email.id : null)} />Получатель мог уже получить письмо. Подтверждаю риск дубля при повторе.</label>}
        {["failed", "uncertain"].includes(email.status) && <Button variant="secondary" size="sm"
          disabled={busy || !options?.enabled || (email.status === "uncertain" && duplicateAck !== email.id)}
          onClick={() => void action(async () => {
            await emailRequest(emailUrl(dealId, `/${email.id}/retry`), { expected_attempt: email.attempt_count, acknowledge_possible_duplicate: duplicateAck === email.id });
            if (mounted.current) setDuplicateAck(null);
            await refresh();
          })}>Повторить это письмо</Button>}
      </article>)}
    </section>}
  </div>;
}
