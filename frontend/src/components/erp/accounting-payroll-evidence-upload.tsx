"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input, Select, Textarea } from "@/components/ui/input";

export type PayrollEvidenceReceipt = {
  file_id: number;
  organization_id: number;
  employment_binding_id: number | null;
  kind: "employment_contract" | "timesheet" | "work_schedule" | "base_adjustment" | "payroll_policy";
  month: string | null;
  reference: string;
  filename: string;
  content_type: string;
  sha256: string;
  size_bytes: number;
  request_key: string;
};

type UploadKind = "employment_contract" | "timesheet" | "work_schedule" | "base_adjustment" | "payroll_policy";
type UploadCommand = {
  request_key: string;
  kind: UploadKind;
  employment_binding_id: number | null;
  month: string | null;
  reference: string;
  filename: string;
  data_url: string;
  evidence: string;
};
type Props = {
  org: string;
  month?: string;
  bindingId?: number;
  contractReference?: string;
  policyOnly?: boolean;
  disabled: boolean;
  onUploaded: (receipt: PayrollEvidenceReceipt) => void;
  onBusyChange?: (busy: boolean) => void;
};

const maxBytes = 10 * 1024 * 1024;
const mimeByExtension: Record<string, string> = {
  pdf: "application/pdf", png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg",
  doc: "application/msword", docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

class UploadError extends Error {
  constructor(message: string, readonly status?: number) { super(message); }
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/accounting${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data && typeof data.detail === "string" ? data.detail : null;
    throw new UploadError(detail ?? `Ошибка загрузки ${response.status}.`, response.status);
  }
  if (data === null) throw new UploadError("Бухгалтерия вернула некорректную квитанцию.");
  return data as T;
}

function readDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Не удалось прочитать выбранный файл."));
    reader.onload = () => {
      if (typeof reader.result !== "string") { reject(new Error("Не удалось прочитать выбранный файл.")); return; }
      resolve(reader.result);
    };
    reader.readAsDataURL(file);
  });
}

function validReceipt(receipt: PayrollEvidenceReceipt, command: UploadCommand, org: string) {
  return receipt.organization_id === Number(org)
    && receipt.employment_binding_id === command.employment_binding_id
    && receipt.kind === command.kind
    && receipt.month === command.month
    && receipt.reference === command.reference
    && receipt.filename === command.filename
    && receipt.content_type === command.data_url.slice(5, command.data_url.indexOf(";base64,"))
    && receipt.request_key === command.request_key
    && receipt.file_id > 0
    && /^[a-f0-9]{64}$/.test(receipt.sha256);
}

export function AccountingPayrollEvidenceUpload({ org, month, bindingId, contractReference, policyOnly = false, disabled, onUploaded, onBusyChange }: Props) {
  const [kind, setKind] = useState<UploadKind>(policyOnly ? "payroll_policy" : "employment_contract");
  const [reference, setReference] = useState("");
  const [evidence, setEvidence] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [pending, setPending] = useState<UploadCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submitting = useRef(false);
  const currentReference = kind === "employment_contract" ? (contractReference ?? "") : reference.trim();

  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);

  async function prepare(): Promise<UploadCommand> {
    if (!policyOnly && (!bindingId || !month)) throw new Error("Выберите договор и месяц источника.");
    if (!file || !file.size || file.size > maxBytes) throw new Error("Выберите файл до 10 МБ.");
    if (!currentReference || currentReference.length > 160 || evidence.trim().length < 10 || file.name.length > 160) throw new Error("Укажите документ и пояснение не короче 10 символов.");
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    const contentType = mimeByExtension[extension];
    if (!contentType) throw new Error("Допустимы PDF, PNG, JPG, DOC, DOCX и XLSX.");
    const rawUrl = await readDataUrl(file);
    const encoded = rawUrl.split(",", 2)[1];
    if (!encoded) throw new Error("Файл не удалось прочитать.");
    return {
      request_key: crypto.randomUUID(), kind, employment_binding_id: policyOnly ? null : bindingId!,
      month: kind === "employment_contract" || kind === "payroll_policy" ? null : month!,
      reference: currentReference, filename: file.name,
      data_url: `data:${contentType};base64,${encoded}`, evidence: evidence.trim(),
    };
  }

  function accept(receipt: PayrollEvidenceReceipt, command: UploadCommand) {
    if (!validReceipt(receipt, command, org)) throw new Error("Квитанция относится к другому юрлицу, области или файлу.");
    setPending(null); setError(""); setNotice(`Файл № ${receipt.file_id} сохранён; байты сверены сервером.`);
    setReference(""); setEvidence(""); setFile(null); setFileInputKey((value) => value + 1);
    onUploaded(receipt);
  }

  async function submit() {
    if (submitting.current || busy || disabled) return;
    submitting.current = true; setBusy(true); setError(""); setNotice("");
    let command = pending;
    let rejectedPost = false;
    try {
      if (!command) { command = await prepare(); setPending(command); }
      const base = `/organizations/${encodeURIComponent(org)}/payroll-evidence-files`;
      try {
        const receipt = await api<PayrollEvidenceReceipt>(base, command);
        accept(receipt, command);
      } catch (cause) {
        if (cause instanceof UploadError && cause.status !== undefined && cause.status < 500 && cause.status !== 408 && cause.status !== 429) { rejectedPost = true; throw cause; }
        try {
          const receipt = await api<PayrollEvidenceReceipt>(`${base}/by-request/${command.request_key}`);
          accept(receipt, command);
        } catch (lookupError) {
          if (lookupError instanceof UploadError && lookupError.status !== 404) throw lookupError;
          throw new Error("Статус загрузки не подтверждён. Повторите сохранённый запрос с тем же ключом.");
        }
      }
    } catch (cause) {
      if (rejectedPost) setPending(null);
      setError(cause instanceof Error ? cause.message : "Файл не сохранён.");
    } finally { submitting.current = false; setBusy(false); }
  }

  const locked = disabled || busy || pending !== null;
  return <div className="space-y-3 rounded-lg border border-line p-3" aria-label={policyOnly ? "Загрузка правил зарплаты" : "Загрузка источника зарплаты"}>
    <h3 className="font-semibold">Добавить подтверждающий документ</h3>
    <p className="text-sm text-muted">{policyOnly ? "Файл правил хранится для выбранного юрлица." : "Файл хранится отдельно для выбранного юрлица и договора."} Квитанция подтверждает байты, но содержание проверяет бухгалтер.</p>
    <div className="grid gap-3 md:grid-cols-2">
      {policyOnly ? <p className="text-sm">Вид документа: правила расчёта зарплаты</p> : <label className="text-sm">Вид документа<Select aria-label="Вид документа" value={kind} disabled={locked} onChange={(event) => { setKind(event.target.value as UploadKind); setError(""); }}><option value="employment_contract">Договор</option><option value="timesheet">Табель за {month}</option><option value="work_schedule">График работы и норма за {month}</option><option value="base_adjustment">Основание корректировки за {month}</option></Select></label>}
      <label className="text-sm">Номер или ссылка на документ<Input aria-label="Номер документа" value={currentReference} disabled={locked || kind === "employment_contract"} onChange={(event) => setReference(event.target.value)} /></label>
    </div>
    <label className="block text-sm">Файл PDF, изображение или Office до 10 МБ<Input key={fileInputKey} aria-label={policyOnly ? "Файл правил зарплаты" : "Файл источника зарплаты"} type="file" accept=".pdf,.png,.jpg,.jpeg,.doc,.docx,.xlsx" disabled={locked} onChange={(event) => setFile(event.target.files?.[0] ?? null)} /></label>
    <label className="block text-sm">Что подтверждает документ<Textarea aria-label="Пояснение документа" value={evidence} disabled={locked} onChange={(event) => setEvidence(event.target.value)} /></label>
    <Button disabled={disabled || busy || (!pending && !file)} onClick={() => void submit()}>{pending ? "Проверить или повторить сохранение" : "Сохранить документ"}</Button>
    {pending && <p className="break-all text-xs text-muted">Ключ запроса: {pending.request_key}. Поля заблокированы до подтверждения результата.</p>}
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}
