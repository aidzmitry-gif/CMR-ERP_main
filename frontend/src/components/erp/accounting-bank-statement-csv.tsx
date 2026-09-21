"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const template = "external_id,direction,operation_date,amount,currency,counterparty_name,counterparty_identifier,purpose\n";
type Preview = {
  organization_id: number; valid: boolean; preview_digest: string; source_reference: string; valid_count: number;
  totals: { receipt: string; payment: string };
  errors: { record: number; message: string }[];
};
type Data = { provider: string; account_code: string; evidence: string; content: string };
type ConfirmCommand = Data & { preview_digest: string };
type Confirmed = { organization_id: number; source_transaction_ids: number[]; count: number; source_reference: string };
type CsvRequestError = Error & { status?: number };

const sha256 = /^[a-f0-9]{64}$/;
const sourceReference = /^sha256:[a-f0-9]{64}$/;
const money = (value: unknown) => typeof value === "string" && /^\d+(?:\.\d+)?$/.test(value);
const plainObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
function errorRow(value: unknown) {
  if (!plainObject(value)) return false;
  const record = value.record;
  return typeof record === "number" && Number.isSafeInteger(record) && record > 0 && typeof value.message === "string" && value.message.length > 0;
}

function previewResult(value: unknown, org: string): asserts value is Preview {
  if (!plainObject(value)) {
    throw new Error("Сервер не подтвердил корректный предварительный расчёт выписки для выбранного юрлица.");
  }
  const validCount = value.valid_count;
  const errors = value.errors;
  if (typeof value.organization_id !== "number" || !Number.isSafeInteger(value.organization_id) || String(value.organization_id) !== org
    || typeof value.valid !== "boolean"
    || typeof value.preview_digest !== "string" || !sha256.test(value.preview_digest)
    || typeof value.source_reference !== "string" || !sourceReference.test(value.source_reference)
    || typeof validCount !== "number" || !Number.isSafeInteger(validCount) || validCount < 0
    || !plainObject(value.totals) || !money(value.totals.receipt) || !money(value.totals.payment)
    || !Array.isArray(errors) || !errors.every(errorRow)
    || (value.valid && (validCount < 1 || errors.length > 0))
    || (!value.valid && errors.length === 0)) {
    throw new Error("Сервер не подтвердил корректный предварительный расчёт выписки для выбранного юрлица.");
  }
}

function confirmationResult(value: unknown, org: string, preview: Preview): asserts value is Confirmed {
  if (!plainObject(value)
    || typeof value.organization_id !== "number" || !Number.isSafeInteger(value.organization_id) || String(value.organization_id) !== org
    || value.source_reference !== preview.source_reference
    || !Number.isSafeInteger(value.count) || value.count !== preview.valid_count
    || !Array.isArray(value.source_transaction_ids) || value.source_transaction_ids.length !== preview.valid_count
    || !value.source_transaction_ids.every((id) => Number.isSafeInteger(id) && id > 0)
    || new Set(value.source_transaction_ids).size !== value.source_transaction_ids.length) {
    throw new Error("Сервер не подтвердил сохранение тех же строк выписки. Результат требует повторной проверки.");
  }
}

async function request(org: string, path: "preview" | "confirm", body: Data | ConfirmCommand): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`/api/accounting/organizations/${org}/bank-statement/csv/${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), cache: "no-store",
    });
  } catch {
    throw new Error("Не удалось получить ответ ERP; результат сохранения выписки пока неизвестен.");
  }
  let result: unknown;
  try { result = await response.json(); }
  catch {
    const error = new Error(response.ok ? "ERP вернула неполный ответ; результат сохранения выписки пока неизвестен." : "ERP вернула неполный ответ об импорте выписки.") as CsvRequestError;
    error.status = response.status;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(plainObject(result) && typeof result.detail === "string" ? result.detail : "Проверьте файл и реквизиты импорта.") as CsvRequestError;
    error.status = response.status;
    throw error;
  }
  return result;
}

function uncertain(error: unknown) {
  const status = (error as CsvRequestError).status;
  return status === undefined || ![400, 401, 403, 404, 409, 413, 415, 422].includes(status);
}

export function AccountingBankStatementCsv({ org, disabled, onImported }: {
  org: string; disabled: boolean; onImported: () => Promise<void>;
}) {
  const [data, setData] = useState<Data>({ provider: "", account_code: "", evidence: "", content: "" });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [retry, setRetry] = useState(false);
  const [frozenConfirm, setFrozenConfirm] = useState<ConfirmCommand | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  function invalidate() {
    setPreview(null); setRetry(false); setFrozenConfirm(null); setMessage(""); setError("");
  }

  async function readFile(file?: File) {
    if (retry) return;
    invalidate();
    setData((current) => ({ ...current, content: "" }));
    if (!file) return;
    if (file.size > 1_000_000) { setError("Файл должен быть не больше 1 МБ."); return; }
    setBusy(true);
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
      if (alive.current) setData((current) => ({ ...current, content }));
    } catch { if (alive.current) setError("Не удалось прочитать CSV в кодировке UTF-8."); }
    finally { if (alive.current) setBusy(false); }
  }

  async function execute(confirm: boolean) {
    if (busy || disabled || (confirm && !preview?.valid)) return;
    const checkedPreview = preview;
    const body: Data | ConfirmCommand = confirm
      ? frozenConfirm ?? { ...data, preview_digest: checkedPreview!.preview_digest }
      : data;
    setBusy(true); setError(""); setMessage("");
    try {
      const result = await request(org, confirm ? "confirm" : "preview", body);
      if (!alive.current) return;
      if (confirm) {
        confirmationResult(result, org, checkedPreview!);
        setPreview(null);
        setRetry(false); setFrozenConfirm(null);
        setMessage(`Обработано строк: ${checkedPreview!.valid_count}. Проводки проверяются и подтверждаются в очереди ниже.`);
        try { await onImported(); }
        catch { if (alive.current) setMessage("Выписка сохранена. Не удалось обновить очередь; обновите раздел банка."); }
      } else {
        previewResult(result, org);
        setPreview(result);
      }
    } catch (e) {
      if (!alive.current) return;
      if (confirm && uncertain(e)) {
        setRetry(true); setFrozenConfirm(body as ConfirmCommand);
        setError("Результат сохранения неизвестен. ERP повторит только ту же неизменённую команду, чтобы проверить её результат без дублей.");
      } else setError(e instanceof Error ? e.message : "Ошибка импорта CSV.");
    }
    finally { if (alive.current) setBusy(false); }
  }

  return <details className="rounded-xl border border-border p-3">
    <summary className="cursor-pointer font-semibold">Загрузить выписку CSV</summary>
    <p className="my-2 text-sm text-muted">До 1000 операций BYN. UTF-8, разделитель — запятая. Направление: receipt — поступление, payment — списание; дата ГГГГ-ММ-ДД, сумма с точкой. Файл банка нужно привести к шаблону. Сохранение не создаёт проводки.</p>
    <a className="text-accent-ink underline" download="bank-statement-template.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(template)}`}>Скачать шаблон CSV</a>
    <fieldset disabled={busy || disabled || retry} className="my-3 grid gap-3 md:grid-cols-2">
      {([{ key: "provider", label: "Банк для CSV", max: 100 }, { key: "account_code", label: "Наш банковский счёт для CSV", max: 64 },
        { key: "evidence", label: "Основание принадлежности счёта для CSV", max: 1000 }] as const).map(({ key, label, max }) =>
        <label key={key}>{label}<Input aria-label={label} maxLength={max} value={data[key]}
          onChange={(event) => { setData({ ...data, [key]: event.target.value }); invalidate(); }} /></label>)}
      <label>Файл CSV<Input aria-label="Файл банковской выписки CSV" type="file" accept=".csv,text/csv" onChange={(event) => void readFile(event.target.files?.[0])} /></label>
    </fieldset>
    <Button disabled={busy || disabled || retry || !org || !data.provider || !data.account_code || !data.evidence.trim() || !data.content} onClick={() => void execute(false)}>Проверить CSV</Button>
    {preview && <div className="my-3 space-y-2">
      <p>Корректных строк: {preview.valid_count}. Поступления: {preview.totals.receipt} BYN; списания: {preview.totals.payment} BYN.</p>
      {preview.errors.length > 0 && <div role="alert" className="max-h-64 overflow-auto text-red-700"><p>Импорт заблокирован. Исправьте все ошибки:</p>{preview.errors.map((item, i) => <p key={i}>Запись {item.record}: {item.message}</p>)}</div>}
      <Button disabled={busy || disabled || !preview.valid} onClick={() => void execute(true)}>{retry ? "Проверить результат сохранения" : "Сохранить строки выписки"}</Button>
    </div>}
    {error && <p role="alert" className="mt-2 text-red-700">{error}</p>}
    {message && <p role="status" className="mt-2 text-money">{message}</p>}
  </details>;
}
