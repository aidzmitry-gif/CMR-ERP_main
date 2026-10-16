"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  EMAIL_REASON,
  EMAIL_STATUS,
  emailRequest,
  emailUrl,
  type DocumentEmail,
  type EmailAttempt,
  type EmailOptions,
  type OutgoingAttachment,
  type UploadPayload,
} from "@/lib/document-email-api";
import {
  fetchIncomingDetail,
  fetchIncomingPage,
  incomingAttachmentUrl,
  type IncomingEmail,
  type IncomingEmailDetail,
} from "@/lib/sales-mail-api";

const MAX_UPLOAD_BYTES = 14 * 1024 * 1024;
const MAX_ATTACHMENTS = 10;
const EXTENSION_TYPES: Record<string, string> = {
  pdf: "application/pdf",
  txt: "text/plain",
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};
const ALLOWED_EXTENSIONS = new Set(Object.keys(EXTENSION_TYPES));
const ALLOWED_TYPES = new Set(Object.values(EXTENSION_TYPES));

const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString("ru-RU") : "—";
const split = (value: string) => value.split(/[;,]/).map((v) => v.trim()).filter(Boolean);
const formatSize = (value: number | null | undefined) => value == null ? "размер не указан" : `${Math.ceil(value / 1024)} КБ`;
const outgoingAttachmentLabel = (file: OutgoingAttachment) => [
  file.number || file.filename,
  ...(file.number && file.version != null ? [`версия ${file.version}`] : []),
  ...(file.document_id != null ? ["PDF"] : []),
  formatSize(file.size),
].join(" · ");

function extension(file: File) {
  return file.name.toLowerCase().split(".").pop() ?? "";
}

function contentType(file: File) {
  return file.type || EXTENSION_TYPES[extension(file)] || "";
}

function isAllowedFile(file: File) {
  const type = contentType(file);
  return ALLOWED_EXTENSIONS.has(extension(file)) && ALLOWED_TYPES.has(type) && (!file.type || file.type === type);
}

async function filePayload(file: File): Promise<UploadPayload> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return { filename: file.name, content_type: contentType(file), content_base64: btoa(binary) };
}

export function DocumentEmailPanel({ dealId }: { dealId: string }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<EmailOptions | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [uploads, setUploads] = useState<File[]>([]);
  const [to, setTo] = useState("");
  const [cc, setCc] = useState("");
  const [subject, setSubject] = useState("Документы по вашей сделке");
  const [body, setBody] = useState("Направляем документы по вашей сделке.");
  const [replyToReceiptId, setReplyToReceiptId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DocumentEmail | null>(null);
  const [history, setHistory] = useState<DocumentEmail[]>([]);
  const [attempts, setAttempts] = useState<Record<string, EmailAttempt[]>>({});
  const [incoming, setIncoming] = useState<IncomingEmail[]>([]);
  const [incomingNextOffset, setIncomingNextOffset] = useState<number | null>(null);
  const [incomingLoading, setIncomingLoading] = useState(false);
  const [incomingDetails, setIncomingDetails] = useState<Record<string, IncomingEmailDetail>>({});
  const [incomingError, setIncomingError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [duplicateAck, setDuplicateAck] = useState<string | null>(null);
  const requestKey = useRef("");
  const locked = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const pending = history.some((email) => ["queued", "sending", "retry_wait"].includes(email.status));

  useEffect(() => {
    if (!open || !pending) return undefined;
    let ignore = false;
    const timer = setInterval(() => {
      void emailRequest<DocumentEmail[]>(emailUrl(dealId)).then((rows) => {
        if (!ignore) setHistory(rows);
      }).catch(() => {
        if (!ignore) setError("Не удалось обновить статус. Показанные данные могут быть устаревшими.");
      });
    }, 3000);
    return () => { ignore = true; clearInterval(timer); };
  }, [dealId, open, pending]);

  function invalidateDraft() {
    requestKey.current = "";
    setPreview(null);
  }

  function startNewMessage() {
    invalidateDraft();
    setReplyToReceiptId(null);
    setTo("");
    setCc("");
    setSubject("Документы по вашей сделке");
    setBody("Направляем документы по вашей сделке.");
    setUploads([]);
  }

  async function action(work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setError(null);
    try {
      await work();
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "Ошибка запроса CRM");
    } finally {
      locked.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  async function refresh() {
    const rows = await emailRequest<DocumentEmail[]>(emailUrl(dealId));
    if (mounted.current) setHistory(rows);
  }

  async function refreshIncoming() {
    setIncomingLoading(true);
    try {
      const page = await fetchIncomingPage(dealId);
      if (mounted.current) {
        setIncoming(Array.isArray(page.items) ? page.items : []);
        setIncomingNextOffset(page.next_offset);
        setIncomingError(null);
      }
    } catch (reason) {
      if (mounted.current) setIncomingError(reason instanceof Error ? reason.message : "Входящие недоступны");
    } finally {
      if (mounted.current) setIncomingLoading(false);
    }
  }

  async function loadMoreIncoming() {
    if (incomingNextOffset == null || incomingLoading) return;
    const offset = incomingNextOffset;
    setIncomingLoading(true);
    try {
      const page = await fetchIncomingPage(dealId, offset);
      if (mounted.current) {
        setIncoming((current) => [...current, ...(Array.isArray(page.items) ? page.items : [])]);
        setIncomingNextOffset(page.next_offset);
        setIncomingError(null);
      }
    } catch (reason) {
      if (mounted.current) setIncomingError(reason instanceof Error ? reason.message : "Не удалось загрузить следующие входящие");
    } finally {
      if (mounted.current) setIncomingLoading(false);
    }
  }

  async function refreshAll() {
    await Promise.all([refresh(), refreshIncoming()]);
  }

  async function show() {
    const initialDraft = options === null;
    setOpen(true);
    await action(async () => {
      const [opts, rows] = await Promise.all([
        emailRequest<EmailOptions>(emailUrl(dealId, "/options")),
        emailRequest<DocumentEmail[]>(emailUrl(dealId)),
      ]);
      if (!mounted.current) return;
      setOptions(opts);
      setHistory(rows);
      if (initialDraft) setSelected(["invoice", "contract"].flatMap((kind) => {
          const doc = opts.documents.find((item) => item.kind === kind && item.available && !item.superseded_by_id);
          return doc ? [doc.id] : [];
        }));
      await refreshIncoming();
    });
  }

  async function prepare() {
    await action(async () => {
      if (!requestKey.current) requestKey.current = crypto.randomUUID();
      const nextKey = requestKey.current;
      const uploadPayloads = await Promise.all(uploads.map(filePayload));
      const email = await emailRequest<DocumentEmail>(emailUrl(dealId, "/prepare"), {
        request_key: nextKey,
        document_ids: selected,
        uploads: uploadPayloads,
        to: split(to),
        cc: split(cc),
        subject,
        body,
        reply_to_receipt_id: replyToReceiptId,
      });
      if (mounted.current) setPreview(email.status === "prepared" ? email : null);
      await refresh();
    });
  }

  async function send(email: DocumentEmail) {
    if (email.can_confirm !== true) return;
    await action(async () => {
      try {
        // An empty object is intentional: emailRequest uses body presence to select POST.
        await emailRequest<DocumentEmail>(emailUrl(dealId, `/${email.id}/send`), {});
      } catch (reason) {
        await refresh().catch(() => undefined);
        throw new Error(`${reason instanceof Error ? reason.message : "Ответ CRM не получен"}. Проверьте историю перед новой отправкой.`);
      }
      requestKey.current = "";
      if (mounted.current) {
        setPreview(null);
        setReplyToReceiptId(null);
      }
      await refresh();
    });
  }

  async function showIncoming(email: IncomingEmail) {
    if (incomingDetails[email.receipt_id]) return;
    await action(async () => {
      const detail = await fetchIncomingDetail(dealId, email.receipt_id);
      if (mounted.current) setIncomingDetails((current) => ({ ...current, [email.receipt_id]: detail }));
    });
  }

  function replyTo(email: IncomingEmailDetail) {
    if (!email.sender) return;
    invalidateDraft();
    setTo(email.sender);
    setCc("");
    setSubject(email.subject.toLowerCase().startsWith("re:") ? email.subject : `Re: ${email.subject || "Без темы"}`);
    setBody("");
    setReplyToReceiptId(email.receipt_id);
  }

  function addUploads(files: File[]) {
    const invalid = files.find((file) => !isAllowedFile(file));
    if (invalid) {
      setError(`Файл «${invalid.name}» имеет запрещённый тип. Разрешены PDF, TXT, PNG, JPEG, DOCX и XLSX.`);
      return;
    }
    const totalSize = [...uploads, ...files].reduce((sum, file) => sum + file.size, 0);
    if (totalSize > MAX_UPLOAD_BYTES) {
      setError("Размер загруженных файлов превышает 14 MiB.");
      return;
    }
    if (selected.length + uploads.length + files.length > MAX_ATTACHMENTS) {
      setError("Можно выбрать не более 10 вложений.");
      return;
    }
    invalidateDraft();
    setError(null);
    setUploads((current) => [...current, ...files]);
  }

  const inputClass = "mt-1 w-full rounded border border-line bg-surface p-2";
  const hasContent = body.trim().length > 0 || selected.length > 0 || uploads.length > 0;
  const attachmentCount = selected.length + uploads.length;

  return <div className="mt-3 border-t border-line pt-3">
    <Button variant="secondary" size="sm" block onClick={() => open ? setOpen(false) : void show()}>Email документов</Button>
    {open && <section aria-label="Отправка документов по email" className="mt-3 space-y-3 text-sm">
      <p className="font-semibold text-ink">Отправка документов по email</p>
      <p className="text-xs text-muted">Письмо сначала подготавливается. Проверьте зафиксированный состав, подпись и адресатов перед отдельным подтверждением.</p>
      {error && <p role="alert" className="rounded border border-line p-2 text-danger">{error}</p>}
      {options?.configuration_error && <p role="status">Настройка отправителя: {options.configuration_error}</p>}
      {options?.signature_configuration_error && <p role="status">Настройка подписи: {options.signature_configuration_error}</p>}
      {options && !options.enabled && <p role="status">Исходящая отправка ещё не включена администратором.</p>}
      {!preview && options && <>
        <p>От: <strong>{options.sender ?? "не настроен"}</strong></p>
        {options.signature_preview && <div className="rounded border border-line bg-sunken p-2">
          <p className="text-xs font-semibold text-muted">Подпись менеджера</p>
          <p className="whitespace-pre-wrap text-xs">{options.signature_preview}</p>
        </div>}
        <fieldset className="space-y-2"><legend className="font-medium">Выпущенные документы</legend>
          {options.documents.length === 0 && <p className="text-muted">Счета и договоры ещё не выпущены.</p>}
          {options.documents.map((doc) => <label key={doc.id} className="flex items-start gap-2">
            <input type="checkbox" checked={selected.includes(doc.id)} disabled={!doc.available || busy}
              onChange={(event) => {
                invalidateDraft();
                setSelected(event.target.checked ? [...selected, doc.id] : selected.filter((id) => id !== doc.id));
              }} />
            <span>{doc.kind === "invoice" ? "Счёт" : "Договор"} {doc.number} · версия {doc.version ?? "не сохранена"}
              {!doc.available && <span className="block text-xs text-muted">Нет доступного выпущенного оригинала</span>}
              {doc.superseded_by_id && <span className="block text-xs text-muted">Историческая версия: выпущена замена</span>}
            </span>
          </label>)}
        </fieldset>
        <label className="block">Файлы (PDF, TXT, PNG, JPEG, DOCX, XLSX)
          <input type="file" multiple accept=".pdf,.txt,.png,.jpg,.jpeg,.docx,.xlsx" disabled={busy}
            onChange={(event) => addUploads(Array.from(event.target.files ?? []))} className={inputClass} />
        </label>
        {uploads.length > 0 && <ul className="space-y-1 text-xs text-muted">
          {uploads.map((file, index) => <li key={`${file.name}-${index}`} className="flex items-center gap-2">
            <span className="min-w-0 flex-1 truncate">{file.name} · {formatSize(file.size)}</span>
            <button type="button" className="text-accent-ink underline" onClick={() => {
              invalidateDraft();
              setUploads((current) => current.filter((_, itemIndex) => itemIndex !== index));
            }}>убрать</button>
          </li>)}
        </ul>}
        <p className="text-xs text-muted">Вложений: {attachmentCount}/{MAX_ATTACHMENTS}. Лимит загруженных файлов: 14 MiB; окончательная проверка выполняется сервером.</p>
        <label className="block">Кому (To)<input type="email" multiple value={to} disabled={busy} onChange={(event) => { invalidateDraft(); setTo(event.target.value); }} className={inputClass} placeholder="client@example.com" /></label>
        <label className="block">Копия (CC)<input type="email" multiple value={cc} disabled={busy} onChange={(event) => { invalidateDraft(); setCc(event.target.value); }} className={inputClass} /></label>
        <label className="block">Тема<input value={subject} maxLength={250} disabled={busy} onChange={(event) => { invalidateDraft(); setSubject(event.target.value); }} className={inputClass} /></label>
        <label className="block">Текст письма<textarea value={body} maxLength={10000} disabled={busy} onChange={(event) => { invalidateDraft(); setBody(event.target.value); }} className={inputClass} /></label>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" disabled={busy} onClick={startNewMessage}>Новое письмо</Button>
          {replyToReceiptId && <Button variant="secondary" size="sm" disabled={busy} onClick={startNewMessage}>Отменить ответ</Button>}
        </div>
        {replyToReceiptId && <p role="status" className="text-xs text-muted">Ответ будет связан с выбранным входящим письмом. Проверьте адресата перед подготовкой.</p>}
        <Button size="sm" disabled={busy || !hasContent || attachmentCount > MAX_ATTACHMENTS || !to.trim() || !options.sender}
          onClick={() => void prepare()}>Подготовить и проверить</Button>
      </>}
      {preview && <div className="space-y-2 rounded border border-line p-3">
        <p className="font-semibold">Подготовлено — не отправлено</p>
        <p>От: {preview.sender}</p><p>Кому: {preview.to.join(", ")}</p><p>Копия: {preview.cc.join(", ") || "нет"}</p>
        <p>Тема: {preview.subject}</p><p className="whitespace-pre-wrap">{preview.body}</p>
        {preview.attachments.map((file, index) => <a key={`${file.filename}-${index}`} className="block text-accent-ink underline" target="_blank" rel="noreferrer"
          href={emailUrl(dealId, `/${preview.id}/attachments/${index}`)}>{outgoingAttachmentLabel(file)}</a>)}
        <p className="text-xs text-muted">Будут отправлены именно этот зафиксированный состав документов и файлы. Приём почтовым сервером не подтверждает доставку или прочтение.</p>
        {preview.can_confirm !== true && <p role="status" className="text-xs text-muted">Подтверждение недоступно для текущей сессии: проверьте права и настройки отправителя.</p>}
        <div className="flex flex-wrap gap-2">{preview.can_confirm === true && <Button size="sm" disabled={busy || options?.enabled !== true} onClick={() => void send(preview)}>Подтвердить отправку</Button>}
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => { invalidateDraft(); }}>Изменить письмо</Button></div>
      </div>}
      <ConversationThread
        dealId={dealId}
        incoming={incoming}
        details={incomingDetails}
        error={incomingError}
        incomingNextOffset={incomingNextOffset}
        incomingLoading={incomingLoading}
        outgoing={history}
        attempts={attempts}
        duplicateAck={duplicateAck}
        busy={busy}
        onOpen={(email) => void showIncoming(email)}
        onReply={replyTo}
        attachmentUrl={(receiptId, index) => incomingAttachmentUrl(dealId, receiptId, index)}
        onLoadMore={() => void loadMoreIncoming()}
        onRefresh={() => void action(refreshAll)}
        onLoadAttempts={(email) => void action(async () => {
          const detail = await emailRequest<DocumentEmail & { attempts: EmailAttempt[] }>(emailUrl(dealId, `/${email.id}`));
          if (mounted.current) setAttempts((current) => ({ ...current, [email.id]: detail.attempts }));
        })}
        onPrepare={(email) => setPreview(email)}
        onDuplicateAck={(emailId) => setDuplicateAck(emailId)}
        onRetry={(email) => void action(async () => {
          await emailRequest(emailUrl(dealId, `/${email.id}/retry`), { expected_attempt: email.attempt_count, acknowledge_possible_duplicate: duplicateAck === email.id });
          if (mounted.current) setDuplicateAck(null);
          await refresh();
        })}
      />
    </section>}
  </div>;
}

type ConversationEntry =
  | { kind: "incoming"; at: string; email: IncomingEmail }
  | { kind: "outgoing"; at: string; email: DocumentEmail };

function ConversationThread({
  dealId,
  incoming,
  details,
  error,
  incomingNextOffset,
  incomingLoading,
  outgoing,
  attempts,
  duplicateAck,
  busy,
  onOpen,
  onReply,
  attachmentUrl,
  onLoadMore,
  onRefresh,
  onLoadAttempts,
  onPrepare,
  onDuplicateAck,
  onRetry,
}: {
  dealId: string;
  incoming: IncomingEmail[];
  details: Record<string, IncomingEmailDetail>;
  error: string | null;
  incomingNextOffset: number | null;
  incomingLoading: boolean;
  outgoing: DocumentEmail[];
  attempts: Record<string, EmailAttempt[]>;
  duplicateAck: string | null;
  busy: boolean;
  onOpen: (email: IncomingEmail) => void;
  onReply: (email: IncomingEmailDetail) => void;
  attachmentUrl: (receiptId: string, index: number) => string;
  onLoadMore: () => void;
  onRefresh: () => void;
  onLoadAttempts: (email: DocumentEmail) => void;
  onPrepare: (email: DocumentEmail) => void;
  onDuplicateAck: (emailId: string | null) => void;
  onRetry: (email: DocumentEmail) => void;
}) {
  const entries: ConversationEntry[] = [
    ...incoming.map((email) => ({ kind: "incoming" as const, at: email.message_date ?? email.received_at, email })),
    ...outgoing.map((email) => ({ kind: "outgoing" as const, at: email.created_at, email })),
  ].sort((left, right) => Date.parse(right.at) - Date.parse(left.at));

  return <section aria-label="Переписка" className="space-y-2">
    <div className="flex items-center justify-between"><h4 className="font-semibold">Переписка</h4>
      <button type="button" disabled={busy || incomingLoading} onClick={onRefresh} className="text-accent-ink">Обновить</button></div>
    {error && <p role="status" className="text-xs text-muted">Входящие: {error}</p>}
    {!error && incoming.length === 0 && <p className="text-xs text-muted">Входящих сообщений по сделке пока нет.</p>}
    {entries.map((entry) => entry.kind === "incoming" ? <IncomingEntry key={`incoming-${entry.email.receipt_id}`} email={entry.email} detail={details[entry.email.receipt_id]} busy={busy} onOpen={onOpen} onReply={onReply} attachmentUrl={attachmentUrl} /> : <OutgoingEntry
      key={`outgoing-${entry.email.id}`}
      email={entry.email}
      dealId={dealId}
      attempts={attempts[entry.email.id]}
      duplicateAck={duplicateAck}
      busy={busy}
      onLoadAttempts={onLoadAttempts}
      onPrepare={onPrepare}
      onDuplicateAck={onDuplicateAck}
      onRetry={onRetry}
    />)}
    {incomingNextOffset != null && <Button variant="secondary" size="sm" disabled={busy || incomingLoading} onClick={onLoadMore}>{incomingLoading ? "Загрузка…" : "Загрузить ещё входящие"}</Button>}
  </section>;
}

function IncomingEntry({
  email,
  detail,
  busy,
  onOpen,
  onReply,
  attachmentUrl,
}: {
  email: IncomingEmail;
  detail?: IncomingEmailDetail;
  busy: boolean;
  onOpen: (email: IncomingEmail) => void;
  onReply: (email: IncomingEmailDetail) => void;
  attachmentUrl: (receiptId: string, index: number) => string;
}) {
  return <article className="rounded border border-line p-3">
    <button type="button" disabled={busy} onClick={() => onOpen(email)} className="w-full text-left">
      <span className="font-medium">{email.subject || "Без темы"}</span>
      <span className="block text-xs text-muted">Входящее · {date(email.message_date ?? email.received_at)} · {email.sender ?? "отправитель не указан"}</span>
      <span className="block text-xs text-muted">Ответственный: {email.owner ?? "не назначен"}</span>
    </button>
    {detail && <div className="mt-2 space-y-2 border-t border-line pt-2">
      <p className="whitespace-pre-wrap text-sm">{detail.body_text || "(пустой текст)"}</p>
      {detail.attachments.map((file) => <div key={`${file.filename}-${file.index}`} className="text-xs">
        {file.downloadable ? <a className="text-accent-ink underline" target="_blank" rel="noreferrer" href={attachmentUrl(detail.receipt_id, file.index)}>{file.filename} · {file.size == null ? "размер не указан" : formatSize(file.size)}</a> : <span>{file.filename} · скачивание заблокировано: {file.blocked_reason ?? "причина не указана"}{file.size != null ? ` · ${formatSize(file.size)}` : ""}</span>}
      </div>)}
      <Button variant="secondary" size="sm" disabled={busy || !detail.sender} onClick={() => onReply(detail)}>Ответить</Button>
    </div>}
  </article>;
}

function OutgoingEntry({
  email,
  dealId,
  attempts,
  duplicateAck,
  busy,
  onLoadAttempts,
  onPrepare,
  onDuplicateAck,
  onRetry,
}: {
  email: DocumentEmail;
  dealId: string;
  attempts?: EmailAttempt[];
  duplicateAck: string | null;
  busy: boolean;
  onLoadAttempts: (email: DocumentEmail) => void;
  onPrepare: (email: DocumentEmail) => void;
  onDuplicateAck: (emailId: string | null) => void;
  onRetry: (email: DocumentEmail) => void;
}) {
  return <article className="space-y-1 rounded border border-line p-3">
    <p className="font-medium">{EMAIL_STATUS[email.status] ?? "Статус не распознан"}</p>
    <p>{email.subject}</p><p>To: {email.to.join(", ")}{email.cc.length > 0 && ` · CC: ${email.cc.join(", ")}`}</p>
    <p className="text-xs text-muted">Исходящее · {date(email.created_at)} · Попыток: {email.attempt_count}</p>
    <details className="text-xs"><summary>Текст письма</summary><p className="mt-1 whitespace-pre-wrap">{email.body}</p></details>
    {email.accepted_at && <p className="text-xs">Принято сервером: {date(email.accepted_at)}. Доставка и прочтение не подтверждены.</p>}
    {email.next_attempt_at && email.status === "retry_wait" && <p className="text-xs">Повтор после: {date(email.next_attempt_at)}</p>}
    {email.last_reason && email.status !== "accepted" && <p>{EMAIL_REASON[email.last_reason] ?? "Проверьте результат попытки в CRM."}</p>}
    {email.can_confirm !== true && email.status === "prepared" && <p className="text-xs text-muted">Подтверждение недоступно для текущей сессии: проверьте права и настройки отправителя.</p>}
    {email.attachments.map((file, index) => <a key={`${file.filename}-${index}`} className="block text-xs text-accent-ink underline" target="_blank" rel="noreferrer"
      href={emailUrl(dealId, `/${email.id}/attachments/${index}`)}>{outgoingAttachmentLabel(file)}</a>)}
    <details className="text-xs text-muted" onToggle={(event) => { if (event.currentTarget.open) onLoadAttempts(email); }}><summary>Попытки и идентификатор</summary><p className="break-all">{email.message_id}</p>
      {attempts?.map((attempt) => <p key={attempt.number} className="mt-1">
        № {attempt.number} · {date(attempt.started_at)} · {EMAIL_STATUS[attempt.status] ?? "Статус не распознан"}
        {attempt.smtp_code && ` · SMTP ${attempt.smtp_code}`}
        {attempt.reason && attempt.status !== "accepted" && ` · ${EMAIL_REASON[attempt.reason] ?? "Ошибка попытки"}`}
      </p>)}
    </details>
    {email.status === "prepared" && email.can_confirm === true && <button type="button" disabled={busy} onClick={() => onPrepare(email)} className="text-accent-ink">Проверить перед отправкой</button>}
    {email.status === "uncertain" && <label className="flex gap-2"><input type="checkbox" checked={duplicateAck === email.id} onChange={(event) => onDuplicateAck(event.target.checked ? email.id : null)} />Получатель мог уже получить письмо. Подтверждаю риск дубля при повторе.</label>}
    {(["failed", "uncertain"] as string[]).includes(email.status) && email.can_retry === true && <Button variant="secondary" size="sm"
      disabled={busy || (email.status === "uncertain" && duplicateAck !== email.id)} onClick={() => onRetry(email)}>Повторить это письмо</Button>}
  </article>;
}
